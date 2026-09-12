# New vastly-simplified orchestrator implementation plan

## simplified orchestrator implementation plan

Yes that's where we want to get to but unfortunately the orchestration dispatch isn't ready for feature requests yet. It is set up for one workflow and that is full new application planning --> gh-init-issue-tracking --> then epic breakdown. And it's still missing:

1. Feature request planning and implementation on an already-started or implemented app
2. Doesn't use or know about the swarm project
3. Needs simplification for the GH issue notification trigger dispatch state pattern (the pattern matching implements a rigidly defined specific cycle through the state pattern: app plan -> gh issue init --> epic breakdown -> implement an epic --> review an epic --> if epics left to implement then ---> implement an epic else breakdown an epic)
4. That orchestration is fully autonomous — so swarm couldn't be supported since you only currently support strictly interactive because of the zcode-specific implementation. (If swarm added support for opencode then it could be used in the orchestration dispatch workflow.)

New orchestration service implementation — the word is SIMPLIFICATION:

Keep:

1. GH app, notifications, and webhook
2. Python webhook listener
3. PromptInfo strongly typed async event queue (able to support any input path; today it's the webhook listener and the planner skill, but anything that can integrate can provide PromptInfo objects to integrate into the rest of this workflow)
4. Replace the orchestrator-service with an ACP host. Then we can hook any ACP client into it to have the orchestration workflow use any pre-configured ACP client (like our configured opencode install on this host, or kilo code CLI, or qwen code, or zcode when it adds support as an autonomous ACP client).

For this first implementation we will use the opencode setup we have configured for the opencode service in orchestrator-service, except not as a system service. The always-on opencode server is overly complicated — we just need to prompt the CLI over ACP.

1. The async event queue handler will have an agent run the match prompt, like we do currently in orchestrator-service, but replacing the complicated explicit state-pattern cycle with a more open-ended agent orchestration prompt that uses pseudo-code or somewhat natural language to instruct the orchestrator agent on what to do (since the models can handle dev workflows end to end so well now)
2. Match prompt agent invokes the chosen prompt through its configured, attached ACP client.
3. We need 2 paths:
   a. New app: create-app-plan and run gh-issue-tracking-init
   b. New feature/existing app: create plan for feature request and add to existing issue tracking infra
4. After planning (and gh-issue-tracking-init, in case 3a.) then invoke the swarm

## simplified orchestrator implementation plan-independent

### ADD

A1. The interactive planning wizard agent/skill from orchestrator-service (use it as the frontend on swarm, i.e. `/swarm` with new param `plan` performs interactive planning with user and then derives goal(s) from that, asks for approval, then _______ (creates plan?), then runs gh-issue-tracking-init to build GH tracking infra, then starts)

A2. Add research & exploration inhibitor inspired by VS Code repo's GPT 5.5 system prompts (`https://code.visualstudio.com/blogs/2026/07/06/optimizing-vscode-coding-harness-model-providers#_treatment-b-large-prompt-sections`), to:
   a. swarm-orchestrator agent def. (for subagent directions not to spend time meandering but to perform the action-oriented execution)
   b. the subagent defs. to reinforce that they never should meander but jump to action-based method
   c. general rules system file
