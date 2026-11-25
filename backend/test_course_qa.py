"""Exercise Q&A persistence, discovery and authorization against real PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from psycopg.errors import ForeignKeyViolation
import app as portal
from postgres_test_support import PostgresTestCase


class CourseQATests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.ids = []
        for name in ('Author', 'Advisor', 'Other'):
            with portal.get_db() as db:
                sid = db.execute("INSERT INTO students(name,program,year) VALUES(%s,'CS','1') RETURNING id", (name,)).fetchone()['id']
                db.execute("INSERT INTO accounts(student_id,email,password_hash) VALUES(%s,%s,'test')", (sid, name+'@example.test'))
                self.ids.append(sid)
        self.author, self.advisor, self.other = [self.client_for(sid) for sid in self.ids]

    def client_for(self, sid):
        client = portal.app.test_client()
        with client.session_transaction() as session:
            session['student_id'] = sid
        return client

    def ask(self, **changes):
        data = {'course_code': 'csc-510', 'title': 'Project advice?', 'body': 'How should we prepare?'}
        data.update(changes)
        response = self.author.post('/api/qa/questions', json=data)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()['question']['id']

    def answer(self, qid, client=None, body='Read the project rubric.'):
        response = (client or self.advisor).post(f'/api/qa/questions/{qid}/answers', json={'body': body, 'author_id': self.ids[2]})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()['answer_id']

    def test_complete_workflow_persists_and_uses_session_identity(self):
        qid = self.ask(author_id=self.ids[2])
        aid = self.answer(qid)
        self.assertEqual(self.author.put(f'/api/qa/questions/{qid}/helpful-answer', json={'answer_id': aid}).status_code, 200)
        portal.initialize_database()
        data = self.other.get(f'/api/qa/questions/{qid}').get_json()
        self.assertEqual(data['question']['author_id'], self.ids[0])
        self.assertEqual(data['question']['course_code'], 'CSC 510')
        self.assertEqual(data['question']['helpful_answer_id'], aid)
        self.assertEqual(data['answers'][0]['author_id'], self.ids[1])
        self.assertNotIn('email', data['question'])

    def test_course_search_body_answer_search_and_status_filters(self):
        qid = self.ask()
        other = self.ask(course_code='CSC 540', title='Database indexes', body='Explain indexing')
        aid = self.answer(qid, body='Try pair programming')
        for query in ('course=CSC510', 'course=csc-510', 'q=prepare', 'q=pair%20programming', 'q=PROJECT'):
            rows = self.author.get('/api/qa/questions?'+query).get_json()['questions']
            self.assertEqual([r['id'] for r in rows], [qid])
        self.author.put(f'/api/qa/questions/{qid}/helpful-answer', json={'answer_id': aid})
        self.assertEqual([r['id'] for r in self.author.get('/api/qa/questions?status=answered').get_json()['questions']], [qid])
        self.assertEqual([r['id'] for r in self.author.get('/api/qa/questions?status=unanswered').get_json()['questions']], [other])
        self.assertEqual(self.author.get('/api/qa/questions?q=%25').get_json()['questions'], [])

    def test_all_routes_require_authenticated_non_revoked_session(self):
        qid = self.ask()
        actions = [('get','/api/qa/questions',None), ('post','/api/qa/questions',{}),
                   ('get',f'/api/qa/questions/{qid}',None), ('post',f'/api/qa/questions/{qid}/answers',{'body':'Help'}),
                   ('put',f'/api/qa/questions/{qid}/helpful-answer',{'answer_id':None})]
        for client in (portal.app.test_client(), self.other):
            if client == self.other:
                with client.session_transaction() as session:
                    session['auth_version'] = 99
            for method, url, body in actions:
                self.assertEqual(getattr(client,method)(url,json=body).status_code,401)

    def test_only_question_author_can_mark_and_clear(self):
        qid = self.ask()
        aid = self.answer(qid)
        url = f'/api/qa/questions/{qid}/helpful-answer'
        for client in (self.advisor, self.other):
            self.assertEqual(client.put(url,json={'answer_id':aid}).status_code,403)
        self.author.put(url,json={'answer_id':aid})
        self.assertEqual(self.author.put(url,json={'answer_id':None}).status_code,200)
        self.assertIsNone(self.author.get(f'/api/qa/questions/{qid}').get_json()['question']['helpful_answer_id'])

    def test_cannot_select_answer_from_another_question_even_directly_in_database(self):
        first, second = self.ask(), self.ask()
        aid = self.answer(first)
        self.assertEqual(self.author.put(f'/api/qa/questions/{second}/helpful-answer',json={'answer_id':aid}).status_code,404)
        with self.assertRaises(ForeignKeyViolation):
            with portal.get_db() as db:
                db.execute('INSERT INTO course_helpful_answers VALUES(%s,%s)',(second,aid))

    def test_invalid_posts_never_create_questions(self):
        bodies = [None, [], {}, {'course_code':'CSC 510','title':'  ','body':'Body'},
                  {'course_code':'invalid','title':'Title','body':'Body'},
                  {'course_code':'CSC 510','title':'T'*161,'body':'Body'},
                  {'course_code':'CSC 510','title':'Title','body':'B'*4001},
                  {'course_code':123,'title':'Title','body':'Body'}]
        for body in bodies:
            self.assertEqual(self.author.post('/api/qa/questions',json=body).status_code,400)
        self.assertEqual(self.author.get('/api/qa/questions').get_json()['questions'],[])

    def test_invalid_answers_and_selection_preserve_existing_state(self):
        qid = self.ask()
        aid = self.answer(qid)
        url = f'/api/qa/questions/{qid}'
        for body in (None, [], {}, {'body':' '}, {'body':'a'*4001}, {'body':True}):
            self.assertEqual(self.advisor.post(url+'/answers',json=body).status_code,400)
        for body in (None, [], {}, {'answer_id':True}, {'answer_id':'1'}, {'answer_id':-1}, {'answer_id':10**30}):
            self.assertEqual(self.author.put(url+'/helpful-answer',json=body).status_code,400)
        self.assertEqual([a['id'] for a in self.author.get(url).get_json()['answers']],[aid])

    def test_missing_and_out_of_range_questions_return_404(self):
        for qid in (99999,10**30):
            url=f'/api/qa/questions/{qid}'
            self.assertEqual(self.author.get(url).status_code,404)
            self.assertEqual(self.author.post(url+'/answers',json={'body':'help'}).status_code,404)
            self.assertEqual(self.author.put(url+'/helpful-answer',json={'answer_id':None}).status_code,404)

    def test_blocked_members_cannot_view_answer_or_discover_threads(self):
        qid = self.ask()
        for blocker, blocked_id in ((self.ids[0],self.ids[1]),(self.ids[1],self.ids[0])):
            with portal.get_db() as db:
                db.execute('DELETE FROM student_blocks')
                db.execute('INSERT INTO student_blocks VALUES(%s,%s,now())',(blocker,blocked_id))
            self.assertEqual(self.advisor.get('/api/qa/questions').get_json()['questions'],[])
            self.assertEqual(self.advisor.get(f'/api/qa/questions/{qid}').status_code,404)
            self.assertEqual(self.advisor.post(f'/api/qa/questions/{qid}/answers',json={'body':'help'}).status_code,404)

    def test_hidden_answers_do_not_leak_through_search_or_counts(self):
        qid=self.ask()
        self.answer(qid,body='Private unique phrase')
        with portal.get_db() as db:
            db.execute('INSERT INTO student_blocks(blocker_id,blocked_id) VALUES(%s,%s)',(self.ids[2],self.ids[1]))
        self.assertEqual(self.other.get('/api/qa/questions?q=unique').get_json()['questions'],[])
        self.assertEqual(self.other.get('/api/qa/questions').get_json()['questions'][0]['answer_count'],0)
        self.assertEqual(self.other.get(f'/api/qa/questions/{qid}').get_json()['answers'],[])

    def test_pagination_is_bounded_without_duplicates(self):
        ids=[self.ask(title=f'Question {i}') for i in range(23)]
        first=self.author.get('/api/qa/questions').get_json()
        self.assertEqual(len(first['questions']),20)
        second=self.author.get('/api/qa/questions?before='+str(first['next_before'])).get_json()
        self.assertIsNone(second['next_before'])
        self.assertEqual([q['id'] for q in first['questions']+second['questions']],list(reversed(ids)))
        for query in ('before=-1','before=abc','before='+str(10**30),'status=invalid','course=bad','q='+'a'*201):
            self.assertEqual(self.author.get('/api/qa/questions?'+query).status_code,400)

    def test_concurrent_selections_leave_exactly_one_helpful_answer(self):
        qid=self.ask()
        answers=[self.answer(qid),self.answer(qid,self.other)]
        barrier=Barrier(2)
        def select(aid):
            client=self.client_for(self.ids[0]);barrier.wait()
            return client.put(f'/api/qa/questions/{qid}/helpful-answer',json={'answer_id':aid}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(select,answers)),[200,200])
        with portal.get_db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM course_helpful_answers WHERE question_id=%s',(qid,)).fetchone()['count'],1)

    def test_browser_roles_have_no_direct_table_access(self):
        with portal.get_db() as db:
            for table in ('course_questions','course_answers','course_helpful_answers'):
                for role in ('anon','authenticated'):
                    row=db.execute('SELECT has_table_privilege(%s,%s,%s) AS allowed',(role,self.schema+'.'+table,'SELECT,INSERT,UPDATE,DELETE')).fetchone()
                    self.assertFalse(row['allowed'])

    def test_answer_capacity_rejects_next_answer_without_changing_rows(self):
        qid = self.ask()
        with portal.get_db() as db:
            db.execute("INSERT INTO course_answers(question_id,author_id,body) SELECT %s,%s,'Advice' FROM generate_series(1,200)", (qid,self.ids[1]))
        response = self.advisor.post(f'/api/qa/questions/{qid}/answers',json={'body':'One more'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(len(self.author.get(f'/api/qa/questions/{qid}').get_json()['answers']),200)

    def test_author_can_replace_helpful_answer_and_hidden_answer_cannot_be_selected(self):
        qid=self.ask()
        first=self.answer(qid)
        second=self.answer(qid,self.other)
        url=f'/api/qa/questions/{qid}/helpful-answer'
        for aid in (first,second):
            self.assertEqual(self.author.put(url,json={'answer_id':aid}).status_code,200)
            self.assertEqual(self.author.get(f'/api/qa/questions/{qid}').get_json()['question']['helpful_answer_id'],aid)
        with portal.get_db() as db:
            db.execute('INSERT INTO student_blocks(blocker_id,blocked_id) VALUES(%s,%s)',(self.ids[0],self.ids[1]))
        self.assertEqual(self.author.put(url,json={'answer_id':first}).status_code,404)
