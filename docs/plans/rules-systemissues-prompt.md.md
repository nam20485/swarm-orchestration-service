# So much for a progressive disclosure-based rules system

Its very efficient- several cases have shown empirically that we are filling < 1% of the total context when using the rules system! In many cases _no_ rules are read and stored beyond the invoked SKILL.md

## Supporting Obsevations

Wow that explains so much of the beahcior ive been seeing. I keep thinking- "it kind of seems like these agents dont have any knowledge of the conventiions and policies in these repos, e.g. push and PR polices, and esp. commit signing.

---

## Big Problems - Rules file system largely ignored

No I dont want to do anymore audits or metrics-collecting (at least not before we implement some fixes or trials)- we aleady know we have non-trivial issues.

## Implementation Plan

Its time to implement:

1. non-optional, "models-choice" rules reading
2. one critical-files canary, so we know if they reading rules (beyond those mentioned in skills md) 

I'd like a solution that enforces reading rules while making use of the progresive disclousure system.

This rules set is designed top be light0-weeight. fromthe beginning, so hopefully we wont kill the context capacities.

Document what you wrote up there, the problems and metrics, as well as the diffeen solutiuons in the table. Then lets do some research (with subagenst if you want) to find and analyze some solution options.