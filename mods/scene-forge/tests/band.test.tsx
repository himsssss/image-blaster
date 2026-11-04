import { expect, test } from 'claude-code/testing'

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
