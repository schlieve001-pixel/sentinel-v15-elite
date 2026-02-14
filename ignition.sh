#!/bin/bash
SESSION="verifuse_v2_core"

# 1. Create Session & Start Engine 4 (API Server) - Top Left
tmux new-session -d -s $SESSION -n 'VeriFuse_Command'
tmux send-keys -t $SESSION:0.0 'uvicorn verifuse_v2.server.api:app --reload --host 0.0.0.0 --port 8000' C-m

# 2. Split Right & Start Engine 1-3 (Pipeline) - Top Right
tmux split-window -h
tmux send-keys -t $SESSION:0.1 'echo "🚀 IGNITING PIPELINE (Engines 1-3)..."' C-m
tmux send-keys -t $SESSION:0.1 'python3 -c "from verifuse_v2.pipeline_manager import Governor; print(Governor().run_pipeline())"' C-m

# 3. Split Bottom Left & Start Vault Monitor - Bottom Left
tmux select-pane -t $SESSION:0.0
tmux split-window -v
tmux send-keys -t $SESSION:0.2 'watch -n 1 "ls -R verifuse_v2/data/"' C-m

# 4. Split Bottom Right & Prep Client - Bottom Right
tmux select-pane -t $SESSION:0.1
tmux split-window -v
tmux send-keys -t $SESSION:0.3 'echo "Waiting for data..."' C-m
tmux send-keys -t $SESSION:0.3 '# Once data appears, run: curl -X POST http://localhost:8000/api/unlock/{SIGNAL_ID}'

# 5. Organize & Attach
tmux select-layout tiled
tmux select-pane -t $SESSION:0.1
tmux attach-session -t $SESSION
