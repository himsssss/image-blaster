import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { ServerStatus } from '../types'

// Bookmarks above the chat for the local Scene Forge app: the app itself plus four of its pages.
const APP = '/Users/himanshusingh/image to 3d scene/image-blaster/forge-app'
const URL_BASE = 'http://localhost:8770'
const PAGES = [
  { key: 'app', label: 'Scene Forge', hash: '', what: 'Scene Forge' },
  { key: 'library', label: 'Library', hash: '#library', what: 'the Scene Forge Library' },
  { key: 'models', label: '3D models', hash: '#models', what: 'Scene Forge 3D models' },
  { key: 'check', label: 'Check', hash: '#check', what: 'the Scene Forge per-object check' },
  { key: 'final', label: 'Final', hash: '#final', what: 'the Scene Forge final project (Blender file, renders)' },
] as const
type Page = (typeof PAGES)[number]

const status = atom({ plugin: 'scene-forge', key: 'status' } as const, 'unknown' as ServerStatus)

async function up($: EngineInterface) {
  try { return (await $.http.fetch(`${URL_BASE}/api/projects`)).ok } catch { return false }
}
async function check($: EngineInterface) {
  const next: ServerStatus = (await up($)) ? 'up' : 'down'
  const was = await read($, status)
  if (was === 'starting' && next === 'down') return    // still booting
  if (was !== next) await update($, status, () => next)
}

// The browser pane can't be driven from a mod, so the button sends the request the person would type;
// Claude then opens the page in the pane, reviewed like any request they make.
async function open($: EngineInterface, p: Page) {
  await $.prompt.submit({ text: `Open ${p.what} (${URL_BASE}/${p.hash}) in the Claude browser pane.`, asUser: true })
}

// Starts the server detached so it outlives this session; a login shell gives the person's PATH (python3 + Pillow).
async function start($: EngineInterface, p: Page) {
  await update($, status, () => 'starting')
  $.ui.toast('Starting Scene Forge…')
  try {
    await $.process.run(['/bin/zsh', '-lc', 'cd "$1" && nohup python3 server.py --port 8770 >> server.log 2>&1 &', 'start', APP],
      { timeoutMs: 10000 })
  } catch {}
  for (let i = 0; i < 20; i++) {
    await $.clock.sleep(500)
    if (await up($)) { await update($, status, () => 'up'); await open($, p); return }
  }
  await update($, status, () => 'down')
  $.ui.toast(`Scene Forge did not start. See ${APP}/server.log`)
}

const dot = (s: ServerStatus) => (s === 'up' ? '●' : s === 'down' ? '○' : '◌')

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await check($)
    $.clock.every(15000, () => check($))
    return started
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const s = await read($, status)
    const { Box, Button, Text } = $.ui.resolve(e)
    const press = (p: Page) => () => (s === 'down' ? start($, p) : open($, p))
    return (
      <Box>
        {PAGES.map((p, i) => (
          <Box key={`b-${p.key}`}>
            {i > 0 ? <Text dimColor> </Text> : null}
            <Button key={p.key} label={i === 0 ? `${dot(s)} ${p.label}` : p.label} onPress={press(p)} />
          </Box>
        ))}
      </Box>
    )
  })
}
