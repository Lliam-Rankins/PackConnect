import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'

async function register(context, name) {
  const email = `qa-${randomUUID()}@example.test`
  const password = 'Fictional browser test password 2026!'
  const response = await context.request.post('/api/auth/register', {
    data: {
      name,
      email,
      password,
      program: 'Computer Science',
      year: 'First Year',
      willing_to_advise: true,
      completed_courses: ['CSC 510'],
    },
  })
  expect(response.status()).toBe(201)
  return { email, password }
}

async function login(page, account) {
  await page.goto('/#/login')
  await page
    .getByRole('textbox', { name: 'Email address', exact: true })
    .fill(account.email)
  await page.getByLabel('Password', { exact: true }).fill(account.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/#\/app$/)
}

async function openBoard(page) {
  const menu = page.getByRole('button', { name: 'Menu', exact: true })
  if (await menu.isVisible()) await menu.click()
  await page.getByRole('link', { name: 'Course Q&A', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Course Q&A board', exact: true }),
  ).toBeVisible()
}

for (const viewport of [
  { width: 390, height: 844 },
  { width: 1280, height: 900 },
]) {
  test(`real two-member question, answer, helpful selection and search at ${viewport.width}px`, async ({
    browser,
  }) => {
    const authorContext = await browser.newContext({
      baseURL: 'http://127.0.0.1:5174',
      viewport,
    })
    const peerContext = await browser.newContext({
      baseURL: 'http://127.0.0.1:5174',
      viewport,
    })
    try {
      const author = await register(authorContext, 'Browser Author')
      const peer = await register(peerContext, 'Browser Peer')
      const authorPage = await authorContext.newPage()
      const peerPage = await peerContext.newPage()
      await login(authorPage, author)
      await login(peerPage, peer)
      await openBoard(authorPage)
      const marker = randomUUID()
      const title = `How should our ${marker} team prepare?`
      await authorPage
        .getByLabel('Question course code', { exact: true })
        .fill('csc-510')
      await authorPage.getByLabel('Question title', { exact: true }).fill(title)
      await authorPage
        .getByLabel('Question details', { exact: true })
        .fill('Share your experience with project planning.')
      await authorPage
        .getByRole('button', { name: 'Post question', exact: true })
        .click()
      await expect(authorPage).toHaveURL(/#\/app\/qa\/\d+$/)
      const threadURL = authorPage.url()
      const qid = threadURL.split('/').at(-1)
      await peerPage.goto(threadURL)
      const advice = `Assign a reviewer. Searchable advice ${marker}`
      await peerPage.getByLabel('Your answer', { exact: true }).fill(advice)
      await peerPage
        .getByRole('button', { name: 'Post answer', exact: true })
        .click()
      await expect(peerPage.getByText(advice, { exact: true })).toBeVisible()
      await expect(
        peerPage.getByRole('button', { name: 'Mark as helpful', exact: true }),
      ).toHaveCount(0)
      const denied = await peerContext.request.put(
        `/api/qa/questions/${qid}/helpful-answer`,
        { data: { answer_id: null } },
      )
      expect(denied.status()).toBe(403)
      await authorPage.reload()
      await authorPage
        .getByRole('button', { name: 'Mark as helpful', exact: true })
        .click()
      await expect(
        authorPage.getByText('Helpful answer selected by the question author', {
          exact: true,
        }),
      ).toBeVisible()
      await authorPage.reload()
      await expect(
        authorPage.getByRole('button', {
          name: 'Clear helpful answer',
          exact: true,
        }),
      ).toBeVisible()
      await authorPage
        .getByRole('link', { name: 'Back to course questions', exact: true })
        .click()
      await authorPage.getByLabel('Course code', { exact: true }).fill('CSC510')
      await authorPage
        .getByLabel('Search questions and answers', { exact: true })
        .fill(`Searchable advice ${marker}`)
      await authorPage
        .getByRole('combobox', { name: 'Answer status', exact: true })
        .selectOption('answered')
      await authorPage
        .getByRole('button', { name: 'Search board', exact: true })
        .click()
      await expect(
        authorPage.getByRole('link', { name: title, exact: true }),
      ).toBeVisible()
      const overflow = await authorPage.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth,
      )
      expect(overflow).toBe(false)
      await authorPage
        .getByLabel('Course code', { exact: true })
        .fill('CSC 540')
      await authorPage
        .getByRole('button', { name: 'Search board', exact: true })
        .click()
      await expect(
        authorPage.getByRole('link', { name: title, exact: true }),
      ).toHaveCount(0)
      const anonymousContext = await browser.newContext({
        baseURL: 'http://127.0.0.1:5174',
      })
      try {
        expect(
          (
            await anonymousContext.request.get(`/api/qa/questions/${qid}`)
          ).status(),
        ).toBe(401)
      } finally {
        await anonymousContext.close()
      }
    } finally {
      await authorContext.close()
      await peerContext.close()
    }
  })
}

test('a small concurrent read burst keeps saved questions intact', async ({
  browser,
}) => {
  const context = await browser.newContext({ baseURL: 'http://127.0.0.1:5174' })
  try {
    const account = await register(context, 'Concurrent Reader')
    const page = await context.newPage()
    await login(page, account)
    const posted = await context.request.post('/api/qa/questions', {
      data: {
        course_code: 'CSC 510',
        title: 'Read burst fixture',
        body: 'Keep this question unchanged.',
      },
    })
    expect(posted.status()).toBe(201)
    const original = (await posted.json()).question
    const start = Date.now()
    const results = await Promise.all(
      Array.from({ length: 12 }, async () => {
        const response = await context.request.get(
          `/api/qa/questions/${original.id}`,
        )
        expect(response.status()).toBe(200)
        const data = await response.json()
        expect(data.question).toEqual(original)
        expect(data.answers).toEqual([])
      }),
    )
    test.info().annotations.push({
      type: 'local-read-burst',
      description: `${results.length} concurrent reads completed in ${Date.now() - start}ms; not a production load benchmark.`,
    })
  } finally {
    await context.close()
  }
})
