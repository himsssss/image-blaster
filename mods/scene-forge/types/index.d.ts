export type ServerStatus = 'unknown' | 'up' | 'down' | 'starting'

declare module 'claude-code' {
  interface PluginState {
    'scene-forge': { status: ServerStatus }
  }
}
