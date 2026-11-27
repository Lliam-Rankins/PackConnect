import { useEffect, useState } from 'react'
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { deferred, request, response, student } from './test/fixtures'

// Keep App mounted as the real hash router does, including Cancel/Save navigation.
function Workspace({ initialRoute = 'app', onUserUpdated = () => {} }) {
  const [route, setRoute] = useState(initialRoute)
  useEffect(() => {
    const navigate = () => setRoute(window.location.hash.slice(2))
    window.addEventListener('hashchange', navigate)
    return () => window.removeEventListener('hashchange', navigate)
  }, [])
  return (
    <App
      user={student}
      route={route}
      onLogout={() => {}}
      onUserUpdated={onUserUpdated}
    />
  )
}

beforeEach(() => {
  fetch.mockImplementation(async (url, options = {}) => {
    if (url.startsWith('/api/courses?'))
      return response({ courses: ['CSC 510', 'CSC 540'] })
    if (url.startsWith('/api/students/search?')) return response([student])
    if (url === '/api/students/1' && !options.method)
      return response({ student })
    if (url === '/api/requests') return response({ requests: [] })
    if (url === '/api/notifications')
      return response({ notifications: [], unread_count: 0 })
    throw new Error(`Unexpected API request: ${options.method || 'GET'} ${url}`)
  })
})

function holdSearch() {
  const pending = deferred()
  const normalFetch = fetch.getMockImplementation()
  fetch.mockImplementation((url, options) =>
    url.startsWith('/api/students/search?')
      ? pending.promise
      : normalFetch(url, options),
  )
  return pending
}
const writes = () =>
  fetch.mock.calls.filter(([, options]) => options?.method === 'PUT')

it('shows advisor ratings and course feedback on the profile page', async () => {
  const normalFetch = fetch.getMockImplementation()
  fetch.mockImplementation((url, options) =>
    url === '/api/students/1' && !options?.method
      ? Promise.resolve(
          response({
            student: {
              ...student,
              review_summary: { review_count: 1, average_rating: 4 },
              reviews: [
                {
                  request_id: 7,
                  rating: 4,
                  course_code: 'CSC 510',
                  comment: 'Helpful course advice.',
                  created_at: request.created_at,
                },
              ],
            },
          }),
        )
      : normalFetch(url, options),
  )
  render(<Workspace initialRoute="app/profile" />)
  expect(
    await screen.findByRole('heading', { name: 'Advice helpfulness' }),
  ).toBeInTheDocument()
  expect(screen.getByText('4.0 / 5')).toBeInTheDocument()
  expect(screen.getByText('1 review')).toBeInTheDocument()
  expect(screen.getByText('Helpful course advice.')).toBeInTheDocument()
})

describe('peer search', () => {
  it('searches with the selected suggestion and preserves advanced filters', async () => {
    const normalFetch = fetch.getMockImplementation()
    fetch.mockImplementation((url, options) =>
      url.startsWith('/api/courses?')
        ? response({
            courses: ['CSC 326', 'CSC 510'],
            titles: {
              'CSC 326': 'Software Engineering',
              'CSC 510': 'Software Engineering',
            },
          })
        : normalFetch(url, options),
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await screen.findByRole('heading', { name: student.name })
    await user.click(screen.getByText('Advanced filters'))
    await user.type(
      screen.getByRole('textbox', { name: 'Program' }),
      'Computer Science',
    )
    const input = screen.getByRole('combobox', { name: 'Course code or title' })
    await user.clear(input)
    await user.type(input, 'software engineering')
    await screen.findByRole('option', {
      name: 'CSC 510 — Software Engineering',
    })
    const searches = () =>
      fetch.mock.calls.filter(([url]) =>
        url.startsWith('/api/students/search?'),
      )
    expect(searches()).toHaveLength(1)
    await user.keyboard('{ArrowUp}{Enter}')
    expect(input).toHaveValue('CSC 510')
    expect(searches()).toHaveLength(1)
    await user.keyboard('{Enter}')
    await waitFor(() => expect(searches()).toHaveLength(2))
    expect(searches()[1][0]).toBe(
      '/api/students/search?course=CSC+510&program=Computer+Science&available=true',
    )
  })

  it('keeps the matching course code in advice requests after a title search', async () => {
    const advisor = {
      ...student,
      id: 2,
      name: 'Jordan Lee',
      completed_courses: ['CSC 540', 'CSC 326'],
    }
    const titleSearch =
      '/api/students/search?course=Software+Engineering&available=true'
    const normalFetch = fetch.getMockImplementation()
    fetch.mockImplementation((url, options) => {
      if (url === titleSearch)
        return response({
          students: [advisor],
          course_codes: ['CSC326', 'CSC510'],
        })
      if (url === '/api/students/2') return response({ student: advisor })
      return normalFetch(url, options)
    })
    const user = userEvent.setup()
    render(<Workspace />)
    await screen.findByRole('heading', { name: student.name })
    const input = screen.getByRole('combobox', { name: 'Course code or title' })
    await user.clear(input)
    await user.type(input, 'Software Engineering')
    await user.click(screen.getByRole('button', { name: 'Find Students' }))
    await screen.findByRole('heading', { name: advisor.name })
    await user.click(screen.getByRole('link', { name: /View Profile/ }))
    const course = await screen.findByRole('textbox', {
      name: 'Course',
      exact: true,
    })
    expect(course).toHaveValue('CSC 326')
  })

  it('shows loading, then matching peers, and submits the entered course', async () => {
    const user = userEvent.setup()
    const pending = holdSearch()
    render(<Workspace />)
    expect(screen.getByText('Searching for students...')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Searching...' })).toBeDisabled()
    pending.resolve(response([student]))
    expect(
      await screen.findByRole('heading', { name: student.name }),
    ).toBeInTheDocument()
    await user.clear(
      screen.getByRole('combobox', { name: 'Course code or title' }),
    )
    await user.type(
      screen.getByRole('combobox', { name: 'Course code or title' }),
      'CSC 540',
    )
    await user.click(screen.getByRole('button', { name: 'Find Students' }))
    expect(fetch).toHaveBeenCalledWith(
      '/api/students/search?course=CSC+540&available=true',
    )
  })

  it('shows an empty result after a submitted search finishes', async () => {
    const user = userEvent.setup()
    render(<Workspace />)
    await screen.findByRole('heading', { name: student.name })
    const pending = holdSearch()
    await user.click(screen.getByRole('button', { name: 'Find Students' }))
    expect(screen.getByText('Searching for students...')).toBeInTheDocument()
    pending.resolve(response([]))
    expect(
      await screen.findByText(
        'No students found. Try another course code or title.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: student.name }),
    ).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Find Students' })).toBeEnabled()
  })

  it.each(['network', 'HTTP'])(
    'shows connection feedback on %s failure and recovers on retry',
    async (failure) => {
      const user = userEvent.setup()
      const pending = holdSearch()
      render(<Workspace />)
      if (failure === 'network')
        pending.resolve(Promise.reject(new TypeError('Failed to fetch')))
      else pending.resolve(response({ error: 'Unavailable' }, 503))
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Could not connect to the Flask backend',
      )
      fetch.mockImplementation(async (url) => {
        if (url.startsWith('/api/students/search?')) return response([student])
        if (url === '/api/requests') return response({ requests: [] })
        if (url === '/api/notifications')
          return response({ notifications: [], unread_count: 0 })
        throw new Error(`Unexpected API request: ${url}`)
      })
      await user.click(screen.getByRole('button', { name: 'Find Students' }))
      expect(
        await screen.findByRole('heading', { name: student.name }),
      ).toBeInTheDocument()
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    },
  )
})

describe('profile editor', () => {
  it('persists capacity and pause settings with numeric and ISO-date values', async () => {
    const user = userEvent.setup()
    const normalFetch = fetch.getMockImplementation()
    let saved = student
    fetch.mockImplementation((url, options) => {
      if (options?.method === 'PUT') {
        saved = {
          ...student,
          ...JSON.parse(options.body),
          availability_status: 'paused',
          accepting_requests: false,
        }
        return Promise.resolve(response({ student: saved }))
      }
      if (url === '/api/students/1')
        return Promise.resolve(response({ student: saved }))
      return normalFetch(url, options)
    })
    render(<Workspace initialRoute="app/profile/edit" />)
    const limit = await screen.findByRole('spinbutton', {
      name: 'Maximum open advice requests',
    })
    await user.clear(limit)
    await user.type(limit, '2')
    fireEvent.change(screen.getByLabelText('Pause new requests until'), {
      target: { value: '2027-01-15' },
    })
    await user.click(screen.getByRole('button', { name: 'Save Profile' }))
    expect(JSON.parse(writes()[0][1].body)).toMatchObject({
      max_open_requests: 2,
      pause_until: '2027-01-15',
    })
    expect(
      await screen.findByText('Paused until Jan 15, 2027 (Eastern time)'),
    ).toBeInTheDocument()
  })

  it('clears a pause and saves an unlimited request capacity', async () => {
    const user = userEvent.setup()
    const normalFetch = fetch.getMockImplementation()
    let saved = { ...student, pause_until: '2027-01-15' }
    fetch.mockImplementation((url, options) => {
      if (options?.method === 'PUT') {
        saved = { ...student, ...JSON.parse(options.body) }
        return Promise.resolve(response({ student: saved }))
      }
      if (url === '/api/students/1')
        return Promise.resolve(response({ student: saved }))
      return normalFetch(url, options)
    })
    render(<Workspace initialRoute="app/profile/edit" />)
    await user.clear(
      await screen.findByRole('spinbutton', {
        name: 'Maximum open advice requests',
      }),
    )
    await user.click(screen.getByRole('button', { name: 'Clear pause' }))
    await user.click(screen.getByRole('button', { name: 'Save Profile' }))
    expect(JSON.parse(writes()[0][1].body)).toMatchObject({
      max_open_requests: null,
      pause_until: null,
    })
    expect(await screen.findByText('No request limit')).toBeInTheDocument()
  })

  it('saves edited fields and prevents duplicate submissions while saving', async () => {
    const user = userEvent.setup()
    const pending = deferred()
    const normalFetch = fetch.getMockImplementation()
    const updated = {
      ...student,
      bio: 'Updated bio',
      completed_courses: ['CSC 510', 'CSC 540'],
    }
    fetch.mockImplementation((url, options) =>
      options?.method === 'PUT' ? pending.promise : normalFetch(url, options),
    )
    const onUserUpdated = vi.fn()
    render(
      <Workspace
        initialRoute="app/profile/edit"
        onUserUpdated={onUserUpdated}
      />,
    )
    const bio = await screen.findByRole('textbox', { name: 'Bio' })
    expect(bio).toHaveValue(student.bio)
    await user.clear(bio)
    await user.type(bio, 'Updated bio')
    await user.clear(screen.getByRole('textbox', { name: 'Completed courses' }))
    await user.type(
      screen.getByRole('textbox', { name: 'Completed courses' }),
      'CSC 510, CSC 540, ',
    )
    await user.dblClick(screen.getByRole('button', { name: 'Save Profile' }))
    expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(writes()).toHaveLength(1)
    expect(writes()[0][0]).toBe('/api/students/1')
    expect(JSON.parse(writes()[0][1].body)).toMatchObject({
      bio: updated.bio,
      completed_courses: updated.completed_courses,
    })
    pending.resolve(response({ student: updated }))
    await waitFor(() => expect(onUserUpdated).toHaveBeenCalledWith(updated))
    await waitFor(() => expect(window.location.hash).toBe('#/app/profile'))
    expect(await screen.findByText('Profile updated.')).toBeInTheDocument()
    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: 'Save Profile' }),
      ).not.toBeInTheDocument(),
    )
  })

  it('discards cancelled edits and restores saved values when reopened', async () => {
    const user = userEvent.setup()
    render(<Workspace initialRoute="app/profile/edit" />)
    const bio = await screen.findByRole('textbox', { name: 'Bio' })
    await user.clear(bio)
    await user.type(bio, 'Unsaved change')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(window.location.hash).toBe('#/app/profile'))
    await user.click(
      await screen.findByRole('button', { name: 'Edit Profile' }),
    )
    expect(await screen.findByRole('textbox', { name: 'Bio' })).toHaveValue(
      student.bio,
    )
    expect(writes()).toHaveLength(0)
  })

  it('keeps edits after an API failure and enables retry', async () => {
    const user = userEvent.setup()
    const normalFetch = fetch.getMockImplementation()
    fetch.mockImplementation((url, options) =>
      options?.method === 'PUT'
        ? Promise.resolve(
            response({ error: 'Session expired. Sign in again.' }, 401),
          )
        : normalFetch(url, options),
    )
    const onUserUpdated = vi.fn()
    render(
      <Workspace
        initialRoute="app/profile/edit"
        onUserUpdated={onUserUpdated}
      />,
    )
    const bio = await screen.findByRole('textbox', { name: 'Bio' })
    await user.type(bio, ' More details.')
    await user.click(screen.getByRole('button', { name: 'Save Profile' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Session expired. Sign in again.',
    )
    expect(bio).toHaveValue(`${student.bio} More details.`)
    expect(screen.getByRole('button', { name: 'Save Profile' })).toBeEnabled()
    expect(onUserUpdated).not.toHaveBeenCalled()
  })
})

describe('peer profile request controls', () => {
  it.each([
    ['paused', '2027-01-15', 'Paused until Jan 15, 2027 (Eastern time)'],
    ['at_capacity', null, 'At capacity — not accepting new requests'],
  ])(
    'shows %s availability and prevents a new request',
    async (status, until, label) => {
      const normalFetch = fetch.getMockImplementation()
      const peer = {
        ...student,
        id: 2,
        accepting_requests: false,
        availability_status: status,
        pause_until: until,
        max_open_requests: 2,
        open_request_count: 2,
      }
      fetch.mockImplementation((url, options) =>
        url === '/api/students/2'
          ? Promise.resolve(response({ student: peer }))
          : normalFetch(url, options),
      )
      render(<Workspace initialRoute="app/students/2" />)
      expect(await screen.findByText(label)).toBeInTheDocument()
      expect(screen.getByText('2 of 2 advice slots in use')).toBeInTheDocument()
      expect(
        screen.queryByRole('button', { name: 'Send request' }),
      ).not.toBeInTheDocument()
    },
  )

  it('preserves chat access when an existing advisor is paused or full', async () => {
    const normalFetch = fetch.getMockImplementation()
    fetch.mockImplementation((url, options) => {
      if (url === '/api/students/2')
        return Promise.resolve(
          response({
            student: {
              ...student,
              id: 2,
              accepting_requests: false,
              availability_status: 'at_capacity',
            },
          }),
        )
      if (url === '/api/requests')
        return Promise.resolve(
          response({ requests: [{ ...request, status: 'accepted' }] }),
        )
      return normalFetch(url, options)
    })
    render(<Workspace initialRoute="app/students/2" />)
    expect(
      await screen.findByRole('link', { name: 'Open chat' }),
    ).toHaveAttribute('href', '#/app/chat/7')
  })

  it('permits a new request after a previous connection was completed', async () => {
    const normalFetch = fetch.getMockImplementation()
    fetch.mockImplementation((url, options) => {
      if (url === '/api/students/2')
        return Promise.resolve(response({ student: { ...student, id: 2 } }))
      if (url === '/api/requests')
        return Promise.resolve(
          response({ requests: [{ ...request, status: 'completed' }] }),
        )
      return normalFetch(url, options)
    })
    render(<Workspace initialRoute="app/students/2" />)
    expect(
      await screen.findByRole('button', { name: 'Send request' }),
    ).toBeInTheDocument()
  })

  it('lets a student send a request to a registered advisor', async () => {
    const user = userEvent.setup()
    const peer = { ...student, id: 2, name: 'Registered Advisor' }
    const normalFetch = fetch.getMockImplementation()
    fetch.mockImplementation((url, options) => {
      if (url === '/api/students/2')
        return Promise.resolve(response({ student: peer }))
      if (url === '/api/requests' && options?.method === 'POST')
        return Promise.resolve(response({ request: { id: 7 } }, 201))
      return normalFetch(url, options)
    })
    render(<Workspace initialRoute="app/students/2" />)
    await user.type(
      await screen.findByRole('textbox', { name: 'Advice topic' }),
      'Projects',
    )
    await user.type(
      screen.getByRole('textbox', { name: 'Your request' }),
      'How should I prepare?',
    )
    await user.click(screen.getByRole('button', { name: 'Send request' }))
    expect(
      await screen.findByText(/Request sent to Registered Advisor/),
    ).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith(
      '/api/requests',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          course_code: 'CSC 510',
          advice_topic: 'Projects',
          message: 'How should I prepare?',
          recipient_id: 2,
        }),
      }),
    )
  })

  it('explains why an old direct link to an unregistered profile cannot receive requests', async () => {
    const normalFetch = fetch.getMockImplementation()
    fetch.mockImplementation((url, options) =>
      url === '/api/students/2'
        ? Promise.resolve(
            response({
              student: { ...student, id: 2, can_receive_requests: false },
            }),
          )
        : normalFetch(url, options),
    )
    render(<Workspace initialRoute="app/students/2" />)
    expect(
      await screen.findByText(/This sample profile has no registered account/),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Send request' }),
    ).not.toBeInTheDocument()
  })
})

describe('advisor recommendations', () => {
  const ranked = [
    {
      ...student,
      id: 5,
      name: 'Zed Zane',
      match: {
        score: 0.9,
        breakdown: {},
        reasons: [
          { type: 'keyword', terms: ['testing', 'flask'] },
          { type: 'rating', average: 4.5, count: 3 },
        ],
      },
    },
    {
      ...student,
      id: 6,
      name: 'Amy Ames',
      match: {
        score: 0.5,
        breakdown: {},
        reasons: [{ type: 'semantic', field: 'advice_topics' }],
      },
    },
  ]
  const recs = () =>
    fetch.mock.calls.filter(([url]) =>
      url.startsWith('/api/students/recommendations?'),
    )
  const searches = () =>
    fetch.mock.calls.filter(([url]) => url.startsWith('/api/students/search?'))
  function mockRecommendations(reply) {
    const normalFetch = fetch.getMockImplementation()
    fetch.mockImplementation((url, options) =>
      url.startsWith('/api/students/recommendations?')
        ? Promise.resolve(reply)
        : normalFetch(url, options),
    )
  }
  async function submitNeed(text, courseText) {
    const user = userEvent.setup()
    render(<Workspace />)
    await screen.findByRole('heading', { name: student.name })
    if (courseText !== undefined) {
      const input = screen.getByRole('combobox', {
        name: 'Course code or title',
      })
      await user.clear(input)
      if (courseText) await user.type(input, courseText)
    }
    await user.type(screen.getByLabelText('What do you need help with?'), text)
    await user.click(screen.getByRole('button', { name: 'Find Students' }))
    return user
  }

  it('limits the need field to 300 characters', async () => {
    render(<Workspace />)
    expect(
      screen.getByLabelText('What do you need help with?'),
    ).toHaveAttribute('maxlength', '300')
  })

  it('uses the plain search endpoint when need is empty', async () => {
    const user = userEvent.setup()
    render(<Workspace />)
    await screen.findByRole('heading', { name: student.name })
    await user.click(screen.getByRole('button', { name: 'Find Students' }))
    await waitFor(() => expect(searches()).toHaveLength(2))
    expect(recs()).toHaveLength(0)
    expect(screen.queryByText('Best match')).not.toBeInTheDocument()
  })

  it('uses the recommendations endpoint and encodes the need', async () => {
    mockRecommendations(response({ students: ranked }))
    await submitNeed('testing & flask?')
    await screen.findByText('Zed Zane')
    expect(recs()).toHaveLength(1)
    expect(recs()[0][0]).toBe(
      '/api/students/recommendations?course=CSC+510&need=testing+%26+flask%3F&available=true',
    )
  })

  it('passes advanced filters to recommendations', async () => {
    mockRecommendations(response({ students: ranked }))
    const user = userEvent.setup()
    render(<Workspace />)
    await screen.findByRole('heading', { name: student.name })
    await user.click(screen.getByText('Advanced filters'))
    await user.type(screen.getByRole('textbox', { name: 'Program' }), 'MSCS')
    await user.type(screen.getByLabelText('What do you need help with?'), 'x')
    await user.click(screen.getByRole('button', { name: 'Find Students' }))
    await screen.findByText('Zed Zane')
    expect(recs()[0][0]).toContain('program=MSCS')
  })

  it('keeps the server ranking instead of sorting by name', async () => {
    mockRecommendations(response({ students: ranked }))
    await submitNeed('testing')
    await screen.findByText('Zed Zane')
    const names = screen.getAllByRole('heading', { level: 4 })
    expect(names.map((h) => h.textContent)).toEqual(['Zed Zane', 'Amy Ames'])
  })

  it('shows reason chips and marks only the top card as best match', async () => {
    mockRecommendations(response({ students: ranked }))
    await submitNeed('testing')
    await screen.findByText('Zed Zane')
    expect(screen.getByText('Mentions testing, flask')).toBeInTheDocument()
    expect(screen.getByText('Rated 4.5 (3 reviews)')).toBeInTheDocument()
    expect(screen.getByText('Similar advice topics')).toBeInTheDocument()
    expect(screen.getAllByText('Best match')).toHaveLength(1)
    const [first] = screen.getAllByRole('article')
    expect(within(first).getByText('Best match')).toBeInTheDocument()
  })

  it('asks for a course when need is given without one', async () => {
    await submitNeed('testing', '')
    expect(
      await screen.findByText(/Enter a course to get recommendations/),
    ).toBeInTheDocument()
    expect(recs()).toHaveLength(0)
  })

  it.each([
    [401, 'Sign in required.'],
    [400, 'need is too long.'],
  ])('shows the endpoint error on %i', async (status, message) => {
    mockRecommendations(response({ error: message }, status))
    await submitNeed('testing')
    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(screen.queryByText(/Could not connect/)).not.toBeInTheDocument()
  })

  it('shows the connection message on a server error', async () => {
    mockRecommendations(response({ error: 'boom' }, 500))
    await submitNeed('testing')
    expect(await screen.findByText(/Could not connect/)).toBeInTheDocument()
  })

  it('refetches recommendations after a profile save in recommendation mode', async () => {
    mockRecommendations(response({ students: ranked }))
    const user = await submitNeed('testing')
    await screen.findByText('Zed Zane')
    const normalFetch = fetch.getMockImplementation()
    fetch.mockImplementation((url, options) =>
      url === '/api/students/1' && options?.method === 'PUT'
        ? Promise.resolve(response({ student }))
        : normalFetch(url, options),
    )
    window.location.hash = '/app/profile/edit'
    await user.click(await screen.findByRole('button', { name: /save/i }))
    await waitFor(() => expect(recs()).toHaveLength(2))
    expect(searches()).toHaveLength(1)
  })
})
