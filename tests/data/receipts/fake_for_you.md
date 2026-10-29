# qa/for-you.md — Word-for-word /review responses

## Before Concept Approval

Running `curl -s -H "Authorization: Bearer <engine token>" http://127.0.0.1:3003/review` when a concept is pending and unapproved:

```
{"ok":true,"on":true,"pendingConcept":{"who":"Concept Artist","prompt":"<concept-prompt>"}}
```

## After Concept Approval

Running `curl -s -H "Authorization: Bearer <engine token>" http://127.0.0.1:3003/review` after the owner has approved the concept:

```
{"ok":true,"on":true}