#!/bin/bash
# SessionStart: ask Claude to open the Scene Forge web app and start its job watcher.
# Stdout is injected into Claude's context. Set SCENE_FORGE_APP=off to skip.
[ "${SCENE_FORGE_APP:-on}" = "off" ] && exit 0
cd "$CLAUDE_PROJECT_DIR" 2>/dev/null || cd "$(dirname "$0")/../.."
[ -f forge-app/server.py ] || exit 0

pending=$(ls worlds/*/forge/queue/*.json 2>/dev/null | xargs grep -l '"status": "pending"' 2>/dev/null | wc -l | tr -d ' ')
cat <<EOF
<scene-forge-app>
The Scene Forge web app is installed in this project (forge-app/, skills scene-forge*, agents scene-forge-*).
Before anything else this session, invoke the \`scene-forge-app\` skill: start the \`scene-forge\` preview
server (port 8770), open it in the Claude browser, and start the job watcher in the background.
Pending jobs waiting in the queue: ${pending}.
If the user's first message is about something unrelated, still start the app + watcher, then answer them.
</scene-forge-app>
EOF
