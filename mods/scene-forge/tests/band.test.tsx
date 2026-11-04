import { expect, mock, test } from 'claude-code/testing'

const SURFACES = ['terminal', 'desktop'] as const

for (const surface of SURFACES) {
  test(`${surface}: the band shows the five Scene Forge bookmarks`, async ($) => {
    const ui = await $.ui.mount({ plugin: 'scene-forge', surface, component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false } })
    expect((await ui.find({ key: 'app' }))?.text).toContain('Scene Forge')
    expect((await ui.find({ key: 'library' }))?.text).toContain('Library')
    expect((await ui.find({ key: 'models' }))?.text).toContain('3D models')
    expect((await ui.find({ key: 'check' }))?.text).toContain('Check')
    expect((await ui.find({ key: 'final' }))?.text).toContain('Final')
  })

  test(`${surface}: each bookmark asks Claude to open its page in the browser pane`, async ($, on) => {
    const sent: string[] = []
    on('prompt.submit', async (_$, e) => { sent.push(e.text); return { text: e.text } })
    on('http.fetch', async () => ({ ok: true, status: 200, headers: {}, body: '[]' }) as never)
    const ui = await $.ui.mount({ plugin: 'scene-forge', surface, component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false } })
    await ui.press({ key: 'library' })
    await ui.press({ key: 'models' })
    await ui.press({ key: 'final' })
    expect(sent.some((t) => t.includes('http://localhost:8770/#library') && t.includes('browser pane'))).toBe(true)
    expect(sent.some((t) => t.includes('http://localhost:8770/#models'))).toBe(true)
    expect(sent.some((t) => t.includes('http://localhost:8770/#final'))).toBe(true)
  })

  test(`${surface}: the band yields to a survey`, async ($, on) => {
    on('ui.render', ($e, e) => { const { Text } = $e.ui.resolve(e); return <Text key="engine">engine band</Text> })
    const ui = await $.ui.mount({ plugin: 'scene-forge', surface, component: 'AbovePrompt', props: { hasSurvey: true, isWorking: false } })
    expect(await ui.find({ key: 'library' })).toBeUndefined()
  })
}

// SCENE_FORGE_DIR wins; without it the app is the forge-app folder of the repo holding mods/scene-forge.
const DIRS = [
  { name: 'SCENE_FORGE_DIR', env: { SCENE_FORGE_DIR: '/opt/forge-app' }, dir: (a: string) => a === '/opt/forge-app' },
  { name: 'the repo beside the mod', env: {}, dir: (a: string) => /[\\/]forge-app$/.test(a) && !/[\\/]mods[\\/]/.test(a) },
]

for (const c of DIRS) {
  test(`a down server is started from ${c.name}`, async ($, on) => {
    mock.env(on, c.env)
    const clock = mock.clock(on)
    let serving = false
    const runs: string[][] = []
    on('session.start', (_, e) => ({ cwd: e.cwd }))
    on('http.fetch', async () => (serving ? { value: { ok: true, status: 200, headers: {}, body: '[]' } } : { deny: 'connection refused' }) as never)
    on('process.run', async (_$, e) => { runs.push([...e.argv]); serving = true; return { value: { exitCode: 0, stdout: '', stderr: '' } } as never })
    on('ui.toast', async () => ({ value: undefined }) as never)
    on('prompt.submit', async (_$, e) => ({ text: e.text }))
    await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
    const ui = await $.ui.mount({ plugin: 'scene-forge', surface: 'desktop', component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false } })
    const pressed = ui.press({ key: 'app' })
    await clock.advance(500)
    await pressed
    expect(runs.length).toBe(1)
    expect(runs[0].some(c.dir)).toBe(true)
  })
}
