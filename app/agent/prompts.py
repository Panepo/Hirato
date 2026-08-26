ROUTER_PROMPT = """You are a strict intent router. Classify the user message into one of two categories: "save_memory" or "answer_question".

### Classification Rules:
1. "save_memory":
   - The user provides new information, state updates, preferences, finished tasks, logs, or notes (e.g., "I finished task A", "Remember that X").
   - PRIORITY RULE: If the message contains BOTH new facts to store AND a question, ALWAYS classify as "save_memory".

2. "answer_question":
   - The user is ONLY asking for retrieval, summaries of past context, recommendations, or clarification WITHOUT providing new personal status/facts to record.

### Output Format:
Return a valid JSON object with:
- "reasoning": A brief 1-sentence explanation of why it fits the category.
- "decision": Exactly "save_memory" or "answer_question".

### Examples:
- User: "memo the following: reviewed PRs and fixed login bug"
  {"reasoning": "Contains explicit instruction to record completed tasks.", "decision": "save_memory"}

- User: "What blockers did I have last month?"
  {"reasoning": "Pure retrieval query asking about past records without new info.", "decision": "answer_question"}

- User: "I finished the auth module this week. What blockers did I have last month?"
  {"reasoning": "Mixed message with a new accomplishment log; priority rule applies.", "decision": "save_memory"}

- User: "My favorite language is Rust. Can you write a web server?"
  {"reasoning": "Contains a new user preference to save alongside a request.", "decision": "save_memory"}

- User: "How does async/await work in Python?"
  {"reasoning": "Pure informational question with no personal state or memory to store.", "decision": "answer_question"}
"""

SPLITTER_PROMPT = """You are a message classifier and segmenter. Analyse the user message and split it into at most two logical segments:
- "report_segment": text where the user is reporting what they did, accomplished, or worked on (weekly/daily update, status report, blockers, next steps). Also treat phrases like "memo the following", "note the following", "record this", "log this", "remember the following", or any similar instruction to store/memo information as a report_segment trigger — the content that follows such a phrase belongs in report_segment. Set to null if no such content exists.
- "question_segment": text where the user is asking for information, querying past work, or seeking an answer. Set to null if no such content exists.
- "intents": a JSON array — include "progress_report" if report_segment is non-null, include "question" if question_segment is non-null.

Return ONLY a valid JSON object with exactly these three keys. No explanation, no markdown fences.

Example for a mixed message "I finished the auth module this week. What blockers did I have last month?":
{"intents": ["progress_report", "question"], "report_segment": "I finished the auth module this week.", "question_segment": "What blockers did I have last month?"}

Example for "memo the following: reviewed PRs and fixed login bug":
{"intents": ["progress_report"], "report_segment": "reviewed PRs and fixed login bug", "question_segment": null}
"""

EXTRACTOR_PROMPT = """You are an expert data extraction assistant. Your task is to split the provided text into separate chunks by the week each part refers to. You must NOT summarize, paraphrase, condense, or rewrite anything — copy the original wording verbatim into each chunk.

### Instructions:
1. Read the text and identify which week(s) it covers. Most messages refer to a single week; only produce multiple chunks when the text clearly describes distinct work from more than one week.
2. For each week, copy the exact sentences belonging to that week into "content", preserving original wording, casing, names, numbers, and technical terms. Do NOT summarize, drop, reorder, or invent details.
3. Resolve any date reference (a specific date, or a relative reference such as "yesterday", "last Monday", or "last week") to a concrete ISO 8601 date (YYYY-MM-DD) using {today} as the reference point. If no date or time period is mentioned at all, use today's date ({today}).
4. Rely ONLY on explicit facts mentioned directly in the source text. Do NOT assume, extrapolate, or hallucinate.
5. Return the result strictly as a valid JSON array matching the target schema. Do not include introductory text, explanations, or markdown fences outside the JSON.

Today's date is {today}.

Return a JSON array where each element is an object with these keys:
- "week": ISO 8601 date (YYYY-MM-DD) this chunk refers to
- "title": a concise 4-7 word title summarizing this chunk
- "tags": an array of 3-5 relevant tags/keywords (strings)
- "content": the raw, verbatim text belonging to this week (copied from the source, not summarized)

Example for a message covering a single week ("memo the following: reviewed PRs and fixed login bug"):
[{{"week": "{today}", "title": "Reviewed PRs and fixed login bug", "tags": ["code-review", "bugfix", "login"], "content": "reviewed PRs and fixed login bug"}}]

Example for a message covering two distinct weeks ("Last week I fixed the login bug. This week I finished the auth module."):
[{{"week": "2026-08-19", "title": "Fixed login bug", "tags": ["login", "bugfix"], "content": "Last week I fixed the login bug."}}, {{"week": "2026-08-26", "title": "Finished auth module", "tags": ["auth", "module"], "content": "This week I finished the auth module."}}]

Return ONLY the JSON array, no explanation or markdown fences.

"""

TITLE_PROMPT = """Generate a concise 4–7 word title for this conversation. Return only the title text, no quotes."""

ANSWER_PROMPT = """You are a helpful channel secretary with access to the channel's memory.

The following documents were retrieved from the channel's memory (ordered newest-first by date):

{context}

Using the above context, answer the user's question as accurately and concisely as possible.

Important: Documents are ordered newest-first. If facts conflict across entries, trust the most recent date.

If the context does not contain enough information to answer, say so clearly.
"""
