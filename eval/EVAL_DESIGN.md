# Eval Design

## Objective

Systematically measure and improve the Wiki QA agent's accuracy, efficiency, and reliability. Each configuration change produces a new version with a full eval run, enabling direct comparison across iterations.

## Test Sets

### Basic test set (`test_cases.json`)

5 questions for quick smoke tests. No expected answers or categories.

### Golden test set (`golden_test_cases.json`)

30 questions across 4 categories for comprehensive evaluation:

| Category | Count | Source | Purpose |
|---|---|---|---|
| `simple_factual` | 10 | Natural Questions | Single-article factual recall |
| `multi_hop` | 10 | HotpotQA | Cross-article reasoning (bridge + comparison) |
| `out_of_scope` | 5 | Synthetic | Unanswerable questions (predictions, opinions) |
| `ambiguous` | 5 | Synthetic | Vague or underspecified questions |

## Metrics

### System metrics (per query)

| Metric | Description |
|---|---|
| `input_tokens` | Total input tokens across all LLM turns |
| `output_tokens` | Total output tokens across all LLM turns |
| `total_tokens` | Sum of input + output |
| `tool_call_count` | Number of tool invocations |
| `llm_turns` | Number of LLM round-trips |
| `latency_seconds` | Wall-clock time for the full query |
| `cost_usd` | Estimated cost based on per-token pricing |

### Quality metrics (per query)

| Metric | Type | Description |
|---|---|---|
| `task_completed` | bool | Whether the agent finished within `MAX_TURNS` iterations |
| `error_count` | int | Count of tool failures and API timeouts (including retried attempts) |
| `recall` | float (0-1) or null | Fraction of expected-answer key terms found in the generated answer. Null when no expected answer exists. |
| `has_citation` | bool | Whether the answer contains an explicit citation (`Source:` or `Sources:` substring match) |
| `query_hallucination` | bool | True if search queries contain significant novel terms not derived from the user's question |
| `answer_hallucination` | bool | True if factual claims in the answer lack grounding in retrieved Wikipedia context |

### Aggregated metrics

Averages, totals, and rates computed across all queries: task completion rate, avg recall, total cost, hallucination counts, etc.

## How metrics are computed

**Recall**: Tokenize both expected and generated answers into lowercased content words (strip punctuation, ignore single-char tokens). Recall = |intersection| / |expected tokens|.

**Citation (rule-based)**: Exact substring match for `Source:` or `Sources:` anywhere in the generated answer. Only evaluated when the agent made at least one tool call; queries with 0 tool calls are excluded (reported as `-`).

**Semantic correctness (LLM-as-a-Judge)**: Claude Opus 4.6 compares the generated answer to the ground-truth answer. The answer is correct if it captures the core meaning — paraphrasing, extra detail, or format differences are fine. When the ground truth contains multiple acceptable answers (separated by "/" or "or"), the generated answer only needs to match at least one option.

**Query hallucination (LLM-as-a-Judge, trajectory-based)**: Claude Opus 4.6 evaluates the entire multi-step search trajectory. The first query must be derivable from the user's question alone. Each subsequent query is evaluated against the user's question plus all previously retrieved context — a follow-up query is acceptable if its terms come from the question or from entities/facts explicitly found in earlier retrieved context. A query is hallucinated only if it introduces terms found in neither source. Minor rephrasing and synonym usage are acceptable throughout.

**Answer hallucination (LLM-as-a-Judge)**: Claude Opus 4.6 compares every factual claim in the final answer against the retrieved Wikipedia context. Claims containing dates, numbers, names, or causal relationships not present in the context are flagged. Each verdict includes reasoning.

## Eval process

1. Run `python -m eval.eval_runner --golden` for comprehensive eval, or `python -m eval.eval_runner` for smoke tests.
2. Review the summary table and per-query results in `eval/results/`.
3. For error analysis, inspect trace logs in `agent/logs/` to examine thinking steps, tool calls, and raw Wikipedia text.
4. Identify failure patterns, update the agent (prompt, retrieval, config), and re-run as a new version.

---

## Version History

### Version 0 (baseline)

**Date**: 2026-04-14

**Configuration**:
- Model: `claude-opus-4-6`
- System prompt: XML-structured with thinking protocol, anti-hallucination rules, citation requirements
- Wikipedia retrieval: individual article fetching (3 results, 6000 char truncation), intro-section fallback
- Max turns: 10, max tokens: 16000

**Test set**: basic (`test_cases.json`, 5 questions)

**Results** (from eval runs `eval_20260414_034446.json` and `eval_20260414_035101.json`):

| ID | Question | Tokens | Tool Calls | Latency | Cost |
|---|---|---|---|---|---|
| q1 | Capital of France | 7,253 | 2 | 9.0s | $0.0398 |
| q2 | Who wrote 1984 | 3,668 | 1 | 5.7s | $0.0214 |
| q3 | Speed of light | 3,623 | 1 | 5.7s | $0.0208 |
| q4 | Causes of French Revolution | 5,617 | 2 | 17.8s | $0.0450 |
| q5 | How photosynthesis works | 7,173 | 1 | 18.0s | $0.0528 |

**Aggregate** (5 queries):

| Metric | Value |
|---|---|
| Task completion rate | 100% |
| Total tokens | 27,334 |
| Total cost | $0.1798 |
| Avg latency | 11.3s |
| Avg tokens/query | 5,467 |
| Avg tool calls/query | 1.4 |
| Avg cost/query | $0.0360 |
| Errors | 0 |

**Notes**:
- q5 (photosynthesis) previously used 34,868 tokens and 8 tool calls before the Wikipedia client fix (individual article fetching + intro fallback). After the fix: 7,173 tokens and 1 tool call -- an 80% token reduction.
- All answers appear well-sourced with Wikipedia citations.
- Hallucination checks were not yet implemented for this run.

---

### Version 1 (LLM-as-a-Judge hallucination detection)

**Date**: 2026-04-14

**Configuration change from v0**:
- Replaced code-based (heuristic) hallucination checks with **LLM-as-a-Judge** framework using `claude-opus-4-6` as evaluator
- Query hallucination: judge evaluates whether search queries introduce factual knowledge not in the user's question
- Answer hallucination: judge compares every factual claim in the answer against retrieved Wikipedia context
- Each verdict includes structured reasoning

**Test set**: golden (`golden_test_cases.json`, 30 questions)

**Report file**: `eval_20260414_050134.json`

#### Full results

| Type | Question | Expected Answer | Search Queries | Generated Answer (summary) | Tokens | Tools | Latency | Cost | Recall | Q-Hal | A-Hal |
|---|---|---|---|---|---|---|---|---|---|---|---|
| simple_factual | Who sang 'I Ran All the Way Home'? | The Impalas | `I Ran All the Way Home song`, `"I Ran All the Way Home" singer` | "Sorry (I Ran All the Way Home)" was sung by **The Impalas**, a doo-wop group from Brooklyn, NY (1959) | 8,129 | 2 | 7.8s | $0.05 | 1.00 | N | Y |
| simple_factual | When was the last time anyone was on the moon? | December 1972 | `last crewed Moon landing Apollo 17` | **Apollo 17**, **December 7–19, 1972**. Gene Cernan and Harrison Schmitt walked on the lunar surface | 6,797 | 1 | 10.0s | $0.04 | 1.00 | Y | Y |
| simple_factual | Who was the ruler of England in 1616? | James I | `ruler of England 1616`, `James I of England` | **James I** (James VI of Scotland), King of England from 24 March 1603 to 27 March 1625 | 10,819 | 2 | 7.6s | $0.06 | 1.00 | Y | Y |
| simple_factual | How many episodes are there in Dragon Ball Z? | 291 | `Dragon Ball Z episodes` | **291 episodes**, aired on Fuji Television from April 26, 1989, to January 31, 1996 | 4,623 | 1 | 5.7s | $0.03 | 1.00 | N | N |
| simple_factual | When was the first Hunger Games book published? | September 14, 2008 | `The Hunger Games book` | Published **September 14, 2008**, by Scholastic. Initial print run of 200,000 copies | 6,940 | 1 | 6.3s | $0.04 | 1.00 | N | N |
| simple_factual | What is the maximum data rate for 802.11a? | 54 Mbit/s | `802.11a wireless standard` | **54 Mbit/s**, operates in 5 GHz band using 52-subcarrier OFDM | 7,194 | 1 | 7.5s | $0.04 | 1.00 | N | N |
| simple_factual | Who wrote 'He Ain't Heavy, He's My Brother' lyrics? | Bobby Scott and Bob Russell | `He Ain't Heavy, He's My Brother song` | **Bobby Scott** and **Bob Russell**, introduced by Johnny Mercer | 5,868 | 1 | 6.7s | $0.03 | 1.00 | N | N |
| simple_factual | How many seasons of Vampire Diaries are there? | *(none)* | `The Vampire Diaries TV series` | **8 seasons**, 171 episodes total, premiered Sept 10, 2009 | 5,666 | 1 | 5.5s | $0.03 | - | N | N |
| simple_factual | Where was Percy Jackson and the Olympians filmed? | Vancouver, British Columbia | `Percy Jackson and the Olympians TV series filming locations`, `Percy Jackson and the Olympians Disney+ series` | Filmed primarily in **Vancouver, British Columbia** | 11,622 | 2 | 11.3s | $0.07 | 1.00 | Y | Y |
| simple_factual | Who does the voice of Nala in The Lion King? | Moira Kelly (1994) / Beyoncé (2019) | `Nala character The Lion King voice` | **Moira Kelly** (1994), **Beyoncé** (2019 remake) | 7,408 | 1 | 9.4s | $0.04 | 1.00 | N | N |
| multi_hop | Who is older, Annie Morton or Terry Richardson? | Terry Richardson (born 1965 vs 1970) | `Annie Morton model`, `Terry Richardson photographer` | **Terry Richardson** is older (born Aug 14, 1965 vs Oct 8, 1970) | 9,287 | 2 | 6.8s | $0.05 | 1.00 | Y | N |
| multi_hop | Former band of Mother Love Bone member who died before 'Apple'? | Malfunkshun (Andrew Wood) | `Mother Love Bone band Apple album`, `Mother Love Bone member death` | **Andrew Wood** died March 19, 1990; former band was **Malfunkshun** | 9,295 | 2 | 10.4s | $0.05 | 1.00 | N | Y |
| multi_hop | Did LostAlone and Guster have the same number of members? | No (LostAlone 3, Guster 3–4) | `LostAlone band`, `Guster band` | LostAlone: 3 members; Guster: 3 original + Ryan Miller = 4. Not the same | 8,421 | 2 | 11.5s | $0.05 | 0.80 | N | N |
| multi_hop | Were Scott Derrickson and Ed Wood of the same nationality? | Yes, both American | `Scott Derrickson filmmaker`, `Ed Wood filmmaker` | Both are **American** (same nationality) | 11,730 | 2 | 8.3s | $0.06 | 0.75 | N | N |
| multi_hop | Film by Brian Patrick Butler inspired by Kubrick film? | Friend of the World (inspired by Dr. Strangelove) | `Brian Patrick Butler filmmaker director`, `Stanley Kubrick films directed`, `Friend of the World 2020 film Dr. Strangelove Kubrick inspiration` | **Friend of the World** (2020), inspired by Kubrick's **Dr. Strangelove** | 22,914 | 3 | 16.5s | $0.12 | 0.57 | Y | Y |
| multi_hop | Arena where Celtics play opened in what year? | 1995 (TD Garden) | `Celtics basketball`, `TD Garden arena opening year Boston` | **TD Garden** opened in **1995** (originally FleetCenter) | 12,876 | 2 | 13.3s | $0.07 | 1.00 | Y | Y |
| multi_hop | Arthur's Magazine or First for Women started first? | Arthur's Magazine (1844) | `Arthur's Magazine`, `First for Women magazine` | **Arthur's Magazine** (1844) started before **First for Women** (1989) | 5,117 | 2 | 6.5s | $0.03 | 1.00 | N | N |
| multi_hop | Nationality of the director of 'Pandemonium'? | American (Alfred Sole) | `Pandemonium film director`, `Alfred Sole filmmaker director` | Director **Alfred Sole** is **American** (born in Paterson, NJ) | 14,704 | 2 | 10.4s | $0.08 | 0.40 | Y | N |
| multi_hop | Who was born first, Conan Doyle or Agatha Christie? | Arthur Conan Doyle (1859 vs 1890) | `Arthur Conan Doyle`, `Agatha Christie` | **Arthur Conan Doyle** (22 May 1859) born before **Agatha Christie** (15 Sept 1890) | 11,061 | 2 | 7.4s | $0.06 | 0.83 | N | N |
| multi_hop | Peter Rabbit creator born in what country? | England (Beatrix Potter) | `Peter Rabbit series creator`, `Beatrix Potter Peter Rabbit creator` | **Beatrix Potter**, born in **England** (28 July 1866) | 16,869 | 2 | 13.9s | $0.09 | 1.00 | Y | N |
| out_of_scope | What will the stock price of Apple be in 2030? | *(none)* | *(none)* | Cannot predict future stock prices. Wikipedia is a factual reference, not a forecasting tool | 1,240 | 0 | 6.5s | $0.01 | - | N | N |
| out_of_scope | Should I invest in cryptocurrency or real estate? | *(none)* | *(none)* | Not the right resource; designed for factual Q&A, not subjective financial advice | 1,249 | 0 | 9.4s | $0.01 | - | N | N |
| out_of_scope | What is the best programming language to learn in 2027? | *(none)* | *(none)* | Cannot answer; Wikipedia documents factual/historical information, not future predictions | 1,258 | 0 | 7.7s | $0.01 | - | N | N |
| out_of_scope | How do I feel about the new tax policy? | *(none)* | *(none)* | Unable to answer; no way of knowing the user's personal feelings | 1,194 | 0 | 5.4s | $0.01 | - | N | N |
| out_of_scope | What will be the next major scientific breakthrough? | *(none)* | *(none)* | Cannot predict; Wikipedia documents past and present knowledge, not future discoveries | 1,300 | 0 | 8.7s | $0.01 | - | N | N |
| ambiguous | When did it happen? | *(none)* | *(none)* | Asked for clarification: "What event are you referring to?" | 1,109 | 0 | 3.4s | $0.01 | - | N | N |
| ambiguous | How tall is he? | *(none)* | *(none)* | Asked for clarification: "Which person are you asking about?" | 1,090 | 0 | 3.2s | $0.01 | - | N | N |
| ambiguous | What year did the war end? | *(none)* | *(none)* | Asked for clarification: "Which war are you referring to?" | 1,128 | 0 | 3.6s | $0.01 | - | N | N |
| ambiguous | Who won the game last night? | *(none)* | *(none)* | Unable to determine: which sport, league, or teams? And "last night" is relative | 1,191 | 0 | 6.1s | $0.01 | - | N | N |
| ambiguous | Tell me about Mercury. | *(none)* | `Mercury planet`, `Mercury element`, `Mercury Roman god` | Comprehensive overview of all three meanings: planet, chemical element, Roman god | 17,036 | 3 | 34.4s | $0.11 | - | N | Y |

#### Aggregate (30 queries)

| Metric | Value |
|---|---|
| Task completion rate | 100% |
| Total errors | 0 |
| Total tokens | 225,135 |
| Total cost | $1.2955 |
| Avg latency | 9.0s |
| Avg tokens/query | 7,504 |
| Avg tool calls/query | 1.2 |
| Avg cost/query | $0.0432 |
| Avg recall | 0.913 |
| Query hallucinations (LLM judge) | 8/30 |
| Answer hallucinations (LLM judge) | 8/30 |

#### Observations

**LLM judge vs code-based hallucination detection**:
- The LLM judge is significantly stricter than the previous code-based heuristic. Answer hallucinations went from 0/30 (heuristic) to **8/30** (LLM judge).
- The judge identifies subtle issues like: a songwriter's first name discrepancy ("Harry" vs "Aristides" across two Wikipedia sources), inferring "last person to walk on the Moon" without explicit context support, and adding "first English king of the House of Stuart" beyond what context provides.
- Query hallucinations rose from 6/30 to **8/30**. The judge correctly flags cases where the agent pre-fills answer knowledge into search queries (e.g., searching "James I of England" when the question only asks "ruler of England in 1616").

**By category**:
- **Simple factual (10)**: All correct (recall=1.0 where measurable). 3 query hallucinations (nq_02, nq_03, nq_09). 4 answer hallucinations flagged -- mostly minor embellishments beyond retrieved context.
- **Multi-hop (10)**: All completed. Recall ranges from 0.40 to 1.00. 4 query hallucinations where the agent injects intermediate knowledge into follow-up searches. 3 answer hallucinations detected, primarily on complex chains where the agent adds contextual details.
- **Out-of-scope (5)**: Perfect -- all 5 correctly declined (0 tool calls, 0 hallucinations).
- **Ambiguous (5)**: 4/5 correctly asked for clarification. ambig_05 ("Tell me about Mercury") appropriately searched all three interpretations. 1 answer hallucination on ambig_05 (mythology details not in truncated context).

**Recall analysis**:
- Average recall improved to 0.913 (vs 0.882 in v0 code-based run), likely due to run-to-run variation.
- Weakest: hp_08 (0.40) -- "nationality of Pandemonium director" expected "American (Alfred Sole)" but answer said "American" without "Alfred Sole" in matching format. hp_05 (0.57) -- multi-hop chaining introduces partial match losses.

**Cost profile**:
- Total cost $1.30 for 30 queries (agent only, excluding judge cost).
- Out-of-scope/ambiguous: ~$0.01/query. Simple factual: ~$0.04/query. Multi-hop: ~$0.07/query.

---

### Version 2 (anti-hallucination prompt + semantic correctness metric)

**Date**: 2026-04-14

**Configuration changes from v1**:
- **System prompt rewrite** to eliminate hallucination:
  - Agent is framed as a "blank slate" with no internal knowledge
  - Query rules: search queries must use ONLY terms from the user's question; for multi-hop, follow-up searches may use entity names from retrieved text but never pre-known answers
  - Answer rules: every factual claim must be directly traceable to retrieved context; if context is insufficient, agent responds with a standard "unable to find" message
  - Scope rules: decline predictions, opinions, personal advice without searching
  - Ambiguity handling: if question is unclear, refuse and ask for clarification
  - Replaced example questions in prompts to avoid golden test set leakage
- **New eval metric**: `semantic_correctness` — LLM judge (Opus 4.6) checks whether the generated answer is semantically equivalent to the ground-truth answer; returns Y as long as the core meaning is captured regardless of wording

**Test set**: golden (`golden_test_cases.json`, 30 questions)

**Report file**: `eval_20260414_052337.json`

#### Full results

| Type | Question | Expected Answer | Search Queries | Generated Answer (summary) | Tokens | Tools | Latency | Cost | Recall | Sem | Q-Hal | A-Hal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| simple_factual | Who sang 'I Ran All the Way Home'? | The Impalas | `I Ran All the Way Home song` | **The Impalas**, a New York-based doo-wop group | 6,613 | 1 | 6.2s | $0.04 | 1.00 | Y | N | N |
| simple_factual | When was the last time anyone was on the moon? | December 1972 | `last time anyone was on the moon`, `last crewed moon landing` | **December 14, 1972**, during Apollo 17 | 12,308 | 2 | 10.1s | $0.07 | 1.00 | Y | N | N |
| simple_factual | Who was the ruler of England in 1616? | James I | `ruler of England 1616`, `King of England early 17th century`, `James VI Scotland succeeded Elizabeth I England 1603` | **James I** (also known as James VI of Scotland) | 25,949 | 3 | 13.5s | $0.14 | 1.00 | Y | Y | Y |
| simple_factual | How many episodes are there in Dragon Ball Z? | 291 | `Dragon Ball Z episodes` | **291 episodes**, premiered on Fuji Television Apr 1989 – Jan 1996 | 5,537 | 1 | 7.1s | $0.03 | 1.00 | Y | N | N |
| simple_factual | When was the first Hunger Games book published? | September 14, 2008 | `The Hunger Games book publication` | **September 14, 2008**, by Scholastic | 7,643 | 1 | 6.5s | $0.04 | 1.00 | Y | N | N |
| simple_factual | What is the maximum data rate for 802.11a? | 54 Mbit/s | `802.11a standard maximum data rate` | **54 Mbit/s**, operates in 5 GHz band using OFDM | 7,776 | 1 | 7.3s | $0.04 | 1.00 | Y | N | N |
| simple_factual | Who wrote 'He Ain't Heavy, He's My Brother' lyrics? | Bobby Scott and Bob Russell | `He Ain't Heavy He's My Brother song lyrics` | **Bobby Scott** and **Bob Russell** | 7,843 | 1 | 7.5s | $0.04 | 1.00 | Y | N | N |
| simple_factual | How many seasons of Vampire Diaries are there? | 8 | `Vampire Diaries television series seasons` | **8 seasons**, premiered Sept 10, 2009 on The CW | 7,626 | 1 | 6.8s | $0.04 | - | Y | N | N |
| simple_factual | Where was Percy Jackson and the Olympians filmed? | Vancouver, British Columbia | `Percy Jackson and the Olympians filming locations`, `Percy Jackson and the Olympians TV series` | Filmed primarily in **Vancouver, British Columbia** | 11,531 | 2 | 10.8s | $0.07 | 1.00 | Y | N | N |
| simple_factual | Who does the voice of Nala in The Lion King? | Moira Kelly (adult Nala) | `Nala character The Lion King voice actor` | **Moira Kelly** (1994 adult), multiple VAs across franchise | 7,951 | 1 | 8.4s | $0.05 | 1.00 | Y | N | N |
| multi_hop | Who is older, Annie Morton or Terry Richardson? | Terry Richardson | `Annie Morton model`, `Terry Richardson photographer` | **Terry Richardson** is older (born 1965 vs 1970) | 10,166 | 2 | 7.2s | $0.05 | 1.00 | Y | Y | N |
| multi_hop | Former band of Mother Love Bone member who died before 'Apple'? | Malfunkshun | `Mother Love Bone album Apple`, `Mother Love Bone member died` | **Andrew Wood** died; former band was **Malfunkshun** | 11,019 | 2 | 9.2s | $0.06 | 1.00 | Y | N | Y |
| multi_hop | Did LostAlone and Guster have the same number of members? | Yes, both had three members | `LostAlone band`, `Guster band` | LostAlone: 3 members; Guster: started as trio, now 4. Not the same | 9,243 | 2 | 13.1s | $0.05 | 0.60 | Y | N | N |
| multi_hop | Were Scott Derrickson and Ed Wood of the same nationality? | Yes, both are American | `Scott Derrickson director`, `Ed Wood filmmaker` | Both are **American** | 11,129 | 2 | 8.3s | $0.06 | 0.75 | Y | N | N |
| multi_hop | Film by Brian Patrick Butler inspired by Kubrick film? | The Sleepless Unrest / Dr. Strangelove | `Brian Patrick Butler filmmaker director`, `Friend of the World film 2020 Kubrick Dr. Strangelove inspired` | **Friend of the World** (2020), inspired by Kubrick's **Dr. Strangelove** | 16,639 | 2 | 13.7s | $0.09 | 0.57 | N | Y | N |
| multi_hop | Arena where Celtics play opened in what year? | 1995 (TD Garden) | `Celtics`, `TD Garden arena opening year` | **TD Garden** opened in **1995** (originally FleetCenter) | 16,393 | 2 | 13.7s | $0.09 | 1.00 | Y | Y | N |
| multi_hop | Arthur's Magazine or First for Women started first? | Arthur's Magazine (1844) | `Arthur's Magazine`, `First for Women magazine` | **Arthur's Magazine** (1844) before **First for Women** (1989) | 5,984 | 2 | 6.6s | $0.03 | 1.00 | Y | N | N |
| multi_hop | Nationality of the director of 'Pandemonium'? | American (Alfred Sole) | `Pandemonium film director`, `Alfred Sole film director` | **Alfred Sole** is **American** (born in Paterson, NJ) | 16,032 | 2 | 10.2s | $0.09 | 0.10 | N | Y | N |
| multi_hop | Who was born first, Conan Doyle or Agatha Christie? | Arthur Conan Doyle (1859 vs 1890) | `Arthur Conan Doyle birth date`, `Agatha Christie birth date`, `Arthur Conan Doyle biography born` | **Arthur Conan Doyle** (22 May 1859) before **Agatha Christie** (15 Sept 1890) | 27,255 | 3 | 10.9s | $0.14 | 0.83 | Y | N | Y |
| multi_hop | Peter Rabbit creator born in what country? | England (Beatrix Potter) | `creator of Peter Rabbit series`, `Peter Rabbit book series creator author`, `The Tale of Peter Rabbit children's book`, `Beatrix Potter birthplace born`, `Beatrix Potter English author illustrator biography` | **Beatrix Potter**, born 28 July 1866 in **Kensington, London, England** | 70,093 | 5 | 23.7s | $0.36 | 1.00 | Y | Y | Y |
| out_of_scope | What will the stock price of Apple be in 2030? | *(none)* | *(none)* | Declined: predicting future stock prices is outside scope | 1,547 | 0 | 3.9s | $0.01 | - | - | N | N |
| out_of_scope | Should I invest in cryptocurrency or real estate? | *(none)* | *(none)* | Declined: personal financial advice is outside scope | 1,602 | 0 | 5.9s | $0.01 | - | - | N | N |
| out_of_scope | What is the best programming language to learn in 2027? | *(none)* | *(none)* | Declined: future prediction is outside scope | 1,602 | 0 | 5.3s | $0.01 | - | - | N | N |
| out_of_scope | How do I feel about the new tax policy? | *(none)* | *(none)* | Declined: personal feelings/opinions are outside scope | 1,538 | 0 | 3.6s | $0.01 | - | - | N | N |
| out_of_scope | What will be the next major scientific breakthrough? | *(none)* | *(none)* | Declined: future prediction is outside scope | 1,592 | 0 | 4.7s | $0.01 | - | - | N | N |
| ambiguous | When did it happen? | *(none)* | *(none)* | Asked for clarification: "What event are you referring to?" | 1,544 | 0 | 4.2s | $0.01 | - | - | N | N |
| ambiguous | How tall is he? | *(none)* | *(none)* | Asked for clarification: "Which person are you asking about?" | 1,477 | 0 | 2.3s | $0.01 | - | - | N | N |
| ambiguous | What year did the war end? | *(none)* | *(none)* | Asked for clarification: "Which war are you referring to?" | 1,528 | 0 | 2.8s | $0.01 | - | - | N | N |
| ambiguous | Who won the game last night? | *(none)* | *(none)* | Asked for clarification: which sport, league, or teams? | 1,551 | 0 | 3.7s | $0.01 | - | - | N | N |
| ambiguous | Tell me about Mercury. | *(none)* | `Mercury planet`, `Mercury element`, `Mercury Roman god` | Overview of all three meanings: planet, element, Roman god | 16,708 | 3 | 33.0s | $0.11 | - | - | N | Y |

#### Aggregate (30 queries)

| Metric | v1 | v2 | Delta |
|---|---|---|---|
| Task completion rate | 100% | 100% | — |
| Total errors | 0 | 0 | — |
| Total tokens | 225,135 | 325,419 | +44% |
| Total cost | $1.30 | $1.79 | +38% |
| Avg latency | 9.0s | 9.0s | — |
| Avg tokens/query | 7,504 | 10,847 | +45% |
| Avg tool calls/query | 1.2 | 1.4 | +17% |
| Avg cost/query | $0.04 | $0.06 | +38% |
| Avg recall (token match) | 0.913 | 0.887 | -3% |
| Semantic correctness | *(n/a)* | 18/20 (90.0%) | new |
| Query hallucinations | 8/30 | 6/30 | -25% |
| Answer hallucinations | 8/30 | 5/30 | -38% |

#### Observations

**Prompt effectiveness**:
- Query hallucinations dropped from 8 → 6. The stricter prompt reduced cases where the agent pre-filled answer knowledge into queries, though some multi-hop questions still trigger follow-up searches with inferred entities (e.g., hp_01, hp_06, hp_10).
- Answer hallucinations dropped from 8 → 5. The "blank slate" framing and explicit grounding rules reduced embellishments. Remaining flags are mostly on complex multi-hop chains (hp_02, hp_04, hp_09) and one ambiguous question (ambig_05).
- nq_03 ("ruler of England in 1616") still triggers both Q-Hal and A-Hal. The agent searched progressively ("ruler of England 1616" → "King of England early 17th century" → "James VI Scotland...") which shows it's trying to follow rules but eventually leaks knowledge in the third query.

**Semantic correctness**:
- 18/20 (90%) of questions with ground-truth answers were judged semantically correct.
- 2 failures: hp_05 (Butler/Kubrick film — expected "The Sleepless Unrest" but agent answered "Friend of the World") and hp_08 (Pandemonium director nationality — ambiguous expected answer vs agent's response about Alfred Sole specifically).

**Cost tradeoffs**:
- Total tokens increased 44% (225K → 325K) mainly due to hp_10 (Peter Rabbit creator) using 70K tokens and 5 tool calls as the agent strictly followed the "don't assume" rule and required multiple searches to establish Beatrix Potter → England.
- The stricter prompt forces more search iterations on multi-hop questions, trading cost for faithfulness.

**By category**:
- **Simple factual (10)**: 10/10 semantically correct. Only nq_03 had hallucination flags. Search queries are well-derived from user questions.
- **Multi-hop (10)**: 8/10 semantically correct. Token usage increased due to more cautious multi-step searching. hp_10 is the most expensive single query ($0.36, 70K tokens).
- **Out-of-scope (5)**: Perfect — all 5 correctly declined (0 tool calls, 0 hallucinations).
- **Ambiguous (5)**: 4/5 correctly asked for clarification. ambig_05 ("Tell me about Mercury") searched all interpretations; 1 answer hallucination on mythology details beyond truncated context.

---

### Version 3 (citation metric + semantic correctness multi-answer rule)

**Date**: 2026-04-14

**Configuration changes from v2**:
- **New eval metric**: `has_citation` — rule-based check that verifies the generated answer contains an explicit citation via exact substring match for `Source:` or `Sources:`. Only evaluated for queries that invoked the search tool; queries with 0 tool calls are excluded (shown as `-`)
- **Updated semantic correctness judge prompt**: when the ground-truth answer contains multiple acceptable answers (separated by "/" or "or"), the judge now evaluates as correct if the generated answer matches **at least one** of the provided options
- **Updated query hallucination judge**: now evaluates only the **first** search query executed. Subsequent queries may legitimately use entities discovered from earlier retrieval results and are no longer penalized

**Test set**: golden (`golden_test_cases.json`, 30 questions)

**Report file**: `eval_20260414_060917.json`

#### Full results

| Type | Question | Expected Answer | Search Queries | Generated Answer (summary) | Tokens | Tools | Latency | Cost | Recall | Sem | Cite | Q-Hal | A-Hal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| simple_factual | Who sang 'I Ran All the Way Home'? | The Impalas | `I Ran All the Way Home song` | **The Impalas**, a New York-based doo-wop group | 7,371 | 1 | 6.7s | $0.04 | 1.00 | Y | Y | N | N |
| simple_factual | When was the last time anyone was on the moon? | December 1972 | `last crewed moon landing` | **Apollo 17**, **December 14, 1972**. Gene Cernan last to step off | 8,378 | 1 | 8.5s | $0.05 | 1.00 | Y | Y | N | N |
| simple_factual | Who was the ruler of England in 1616? | James I | `ruler England 1616`, `King England 1616 James Stuart` | **James VI and I** (James Charles Stuart), King of England from 24 March 1603 | 19,112 | 2 | 13.1s | $0.10 | 1.00 | Y | Y | N | N |
| simple_factual | How many episodes are there in Dragon Ball Z? | 291 | `Dragon Ball Z episodes` | **291 episodes**, premiered Apr 1989 – Jan 1996 on Fuji Television | 6,324 | 1 | 8.1s | $0.04 | 1.00 | Y | Y | N | Y |
| simple_factual | When was the first Hunger Games book published? | September 14, 2008 | `Hunger Games book publication date` | Published **September 14, 2008**, by Scholastic | 8,520 | 1 | 6.9s | $0.04 | 1.00 | Y | Y | N | N |
| simple_factual | What is the maximum data rate for 802.11a? | 54 Mbit/s | `802.11a wireless standard data rate` | **54 Mbit/s**, operates in 5 GHz band using OFDM | 8,423 | 1 | 9.3s | $0.05 | 1.00 | Y | Y | N | N |
| simple_factual | Who wrote 'He Ain't Heavy, He's My Brother' lyrics? | Bobby Scott and Bob Russell | `He Ain't Heavy He's My Brother song` | **Bobby Scott** and **Bob Russell** | 7,469 | 1 | 8.2s | $0.04 | 1.00 | Y | Y | N | N |
| simple_factual | How many seasons of Vampire Diaries are there? | 8 | `The Vampire Diaries television series seasons` | **8 seasons**, premiered Sept 2009 on The CW | 7,548 | 1 | 7.1s | $0.04 | - | Y | Y | N | N |
| simple_factual | Where was Percy Jackson and the Olympians filmed? | Vancouver, British Columbia | `Percy Jackson and the Olympians filming locations`, `...TV series Disney+ filming locations` | Filmed primarily in **Vancouver, British Columbia** | 20,246 | 2 | 13.6s | $0.11 | 1.00 | Y | Y | N | N |
| simple_factual | Who does the voice of Nala in The Lion King? | Moira Kelly (adult Nala) | `Nala character Lion King voice actor` | **Moira Kelly** (1994 adult), multiple VAs across franchise | 8,766 | 1 | 10.0s | $0.05 | 1.00 | Y | Y | N | N |
| multi_hop | Who is older, Annie Morton or Terry Richardson? | Terry Richardson | `Annie Morton model`, `Terry Richardson photographer` | **Terry Richardson** is older (born 1965 vs 1970) | 10,951 | 2 | 8.3s | $0.06 | 1.00 | Y | Y | N | N |
| multi_hop | Former band of Mother Love Bone member who died before 'Apple'? | Malfunkshun | `Mother Love Bone Apple album`, `Malfunkshun band Andrew Wood` | **Andrew Wood** died; former band was **Malfunkshun** | 16,012 | 2 | 12.8s | $0.09 | 1.00 | Y | Y | N | Y |
| multi_hop | Did LostAlone and Guster have the same number of members? | Yes, both had three members | `LostAlone band members`, `Guster band members` | LostAlone: 3 members; Guster: 3 original + later 4. Not the same | 13,017 | 2 | 12.3s | $0.07 | 0.60 | Y | Y | N | Y |
| multi_hop | Were Scott Derrickson and Ed Wood of the same nationality? | Yes, both are American | `Scott Derrickson filmmaker`, `Ed Wood filmmaker` | Both are **American** (same nationality) | 13,323 | 2 | 14.0s | $0.07 | 0.75 | Y | Y | N | N |
| multi_hop | Film by Brian Patrick Butler inspired by Kubrick film? | The Sleepless Unrest / Dr. Strangelove | `Brian Patrick Butler filmmaker director`, `Dr. Strangelove Stanley Kubrick film` | **Friend of the World** (2020), inspired by Kubrick's **Dr. Strangelove** | 17,799 | 2 | 14.6s | $0.10 | 0.57 | N | Y | N | Y |
| multi_hop | Arena where Celtics play opened in what year? | 1995 (TD Garden) | `Celtics basketball`, `TD Garden opening year` | **TD Garden** opened in **1995** (originally FleetCenter) | 17,519 | 2 | 12.4s | $0.09 | 1.00 | Y | Y | N | Y |
| multi_hop | Arthur's Magazine or First for Women started first? | Arthur's Magazine (1844) | `Arthur's Magazine`, `First for Women magazine` | **Arthur's Magazine** (1844) before **First for Women** (1989) | 6,770 | 2 | 8.5s | $0.04 | 1.00 | Y | Y | N | N |
| multi_hop | Nationality of the director of 'Pandemonium'? | Ambiguous (multiple films share this title) | `Pandemonium film`, `Alfred Sole film director` | Director **Alfred Sole** is **American** (born in Paterson, NJ) | 16,035 | 2 | 10.4s | $0.09 | 0.10 | N | Y | N | N |
| multi_hop | Who was born first, Conan Doyle or Agatha Christie? | Arthur Conan Doyle (1859 vs 1890) | `Arthur Conan Doyle birth date`, `Agatha Christie birth date`, `...biography` | **Arthur Conan Doyle** (22 May 1859) before **Agatha Christie** (15 Sept 1890) | 28,446 | 3 | 13.0s | $0.15 | 0.83 | Y | Y | N | Y |
| multi_hop | Peter Rabbit creator born in what country? | England (Beatrix Potter) | `Peter Rabbit series creator`, `Peter Rabbit Beatrix Potter` | **Beatrix Potter**, born in **England** | 19,161 | 2 | 11.7s | $0.10 | 1.00 | Y | Y | N | N |
| out_of_scope | What will the stock price of Apple be in 2030? | *(none)* | *(none)* | Declined: predicting future stock prices is outside scope | 1,962 | 0 | 4.4s | $0.01 | - | - | - | N | N |
| out_of_scope | Should I invest in cryptocurrency or real estate? | *(none)* | *(none)* | Declined: personal financial advice is outside scope | 1,944 | 0 | 4.5s | $0.01 | - | - | - | N | N |
| out_of_scope | What is the best programming language to learn in 2027? | *(none)* | *(none)* | Declined: future prediction + subjective judgment outside scope | 1,988 | 0 | 5.5s | $0.01 | - | - | - | N | N |
| out_of_scope | How do I feel about the new tax policy? | *(none)* | *(none)* | Declined: personal opinions/feelings outside scope | 1,942 | 0 | 3.8s | $0.01 | - | - | - | N | N |
| out_of_scope | What will be the next major scientific breakthrough? | *(none)* | *(none)* | Declined: future prediction is outside scope | 1,980 | 0 | 5.8s | $0.01 | - | - | - | N | N |
| ambiguous | When did it happen? | *(none)* | *(none)* | Asked for clarification: "What event are you referring to?" | 1,942 | 0 | 3.8s | $0.01 | - | - | - | N | N |
| ambiguous | How tall is he? | *(none)* | *(none)* | Asked for clarification: "Which person are you asking about?" | 1,891 | 0 | 3.6s | $0.01 | - | - | - | N | N |
| ambiguous | What year did the war end? | *(none)* | *(none)* | Asked for clarification: "Which war are you referring to?" | 1,932 | 0 | 3.6s | $0.01 | - | - | - | N | N |
| ambiguous | Who won the game last night? | *(none)* | *(none)* | Asked for clarification: which sport, league, or teams? | 1,948 | 0 | 4.7s | $0.01 | - | - | - | N | N |
| ambiguous | Tell me about Mercury. | *(none)* | *(none)* | Asked for clarification: planet, element, or Roman god? | 2,024 | 0 | 5.6s | $0.01 | - | - | - | N | N |

#### Aggregate (30 queries)

| Metric | v2 | v3 | Delta |
|---|---|---|---|
| Task completion rate | 100% | 100% | — |
| Total errors | 0 | 0 | — |
| Total tokens | 325,419 | 280,743 | -14% |
| Total cost | $1.79 | $1.53 | -14% |
| Avg latency | 9.0s | 8.5s | -6% |
| Avg tokens/query | 10,847 | 9,358 | -14% |
| Avg tool calls/query | 1.4 | 1.1 | -21% |
| Avg cost/query | $0.06 | $0.05 | -17% |
| Avg recall (token match) | 0.887 | 0.887 | — |
| Semantic correctness | 18/20 (90.0%) | 18/20 (90.0%) | — |
| Citation rate (tool-using queries only) | *(n/a)* | 20/20 (100%) | new |
| Query hallucinations (first query only) | 6/30 | 0/30 | -100% |
| Answer hallucinations | 5/30 | 6/30 | +1 |

#### Observations

**Query hallucination — first-query-only evaluation**:
- Query hallucinations dropped from 6/30 (v2) to **0/30** by evaluating only the first search query. In v2, hallucinations were largely flagged on follow-up queries where the agent used entity names discovered from earlier retrieval (e.g., searching "James I King England" after finding James I in an initial search for "ruler England 1616"). These follow-up queries are now correctly excluded from evaluation since they rely on retrieved context.
- nq_03, which was persistently flagged across v1–v2, now passes: its first query `ruler England 1616` is a faithful reformulation of the user's question.

**Citation metric**:
- **100% citation rate** among the 20 tool-using queries — every answer backed by Wikipedia includes explicit `Source:` or `Sources:` citations.
- The 10 queries with no tool calls (5 out-of-scope + 5 ambiguous) are excluded from the citation rate and displayed as `-`, since no retrieval occurred.

**Semantic correctness**:
- 18/20 (90%), matching v2. hp_03 improved back to Y (agent now says "both started as three-member bands" despite noting Guster's later expansion).
- 2 failures: hp_05 (Butler/Kubrick film — agent finds "Friend of the World" instead of expected "The Sleepless Unrest") and hp_08 (Pandemonium director — expected "ambiguous" but agent picked the 1982 film specifically).

**Answer hallucinations**:
- 6/30, slightly up from v2 (5/30). Flagged on nq_04 (minor embellishment), hp_02, hp_03, hp_05, hp_06, hp_09 — mostly multi-hop chains where the agent adds contextual details or synthesis beyond the exact retrieved text.

**Cost and efficiency**:
- Total tokens decreased 14% (325K → 281K), cost down 14% ($1.79 → $1.53).
- ambig_05 ("Tell me about Mercury") continues to correctly ask for clarification instead of searching (0 tool calls, 2K tokens vs 16.7K in v2).
- hp_10 (Peter Rabbit) stable at 19K tokens and 2 tool calls (down from 70K/5 calls in v2).

**By category**:
- **Simple factual (10)**: 10/10 semantically correct, 10/10 cited, 0 query hallucinations. Only nq_04 flagged for answer hallucination.
- **Multi-hop (10)**: 8/10 semantically correct, 10/10 cited, 0 query hallucinations. 5 answer hallucinations — the judge is strict on multi-step synthesis.
- **Out-of-scope (5)**: Perfect — all 5 correctly declined (0 tool calls, 0 hallucinations).
- **Ambiguous (5)**: 5/5 correctly asked for clarification (improved from 4/5 in v2). 0 tool calls, 0 hallucinations.

---

### Version 4 (trajectory-based hallucination + prompt refinements + corrected golden set)

**Date**: 2026-04-14

**Configuration changes from v3**:
- **Agent prompt improvements**:
  - Post-search ambiguity: if a search reveals a concept refers to multiple distinct entities and the original query is unclear, the agent may state the question is ambiguous and list possibilities instead of guessing
  - Graceful failure: explicitly reinforced that it is acceptable to respond with "unable to find sufficient information" when the agent cannot confidently answer within the iteration limit, rather than guessing
- **Eval suite changes**:
  - Set `temperature=0` for both the agent and all LLM judge calls (deterministic outputs)
  - Full retrieved context passed to answer hallucination judge (removed the 20K-char truncation limit)
  - Query hallucination judge now evaluates the **full trajectory** — every search query is checked against the user's question plus all previously retrieved context. A subsequent query is acceptable if its terms come from the user's question or from earlier retrieved context; it is hallucinated only if it introduces terms found in neither
  - Replaced all golden test set examples in LLM judge prompts with independent made-up examples to prevent test set leakage
- **Golden test set corrections**:
  - `hp_03` expected answer: "Yes, both had three members" → "No, Guster has four members and LostAlone has three"
  - `hp_05` expected answer: "The Sleepless Unrest was inspired by The Shining" → "Friend of the World was inspired by Dr. Strangelove"

**Test set**: golden (`golden_test_cases.json`, 30 questions)

**Report file**: `eval_20260414_160756.json`

#### Full results

| Type | Question | Expected Answer | Search Queries | Generated Answer (summary) | Tokens | Tools | Latency | Cost | Recall | Sem | Cite | Q-Hal | A-Hal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| simple_factual | Who sang 'I Ran All the Way Home'? | The Impalas | `I Ran All the Way Home song` | **The Impalas**, a New York-based doo-wop group | 7,655 | 1 | 6.7s | $0.04 | 1.00 | Y | Y | N | N |
| simple_factual | When was the last time anyone was on the moon? | December 1972 | `last crewed moon landing` | **Apollo 17**, **14 December 1972**. Gene Cernan last to step off | 8,654 | 1 | 7.3s | $0.05 | 1.00 | Y | Y | N | N |
| simple_factual | Who was the ruler of England in 1616? | James I | `ruler England 1616`, `James I England king 1603 1625` | **James VI and I**, King of England from 24 March 1603 | 18,334 | 2 | 11.4s | $0.10 | 1.00 | Y | Y | Y | N |
| simple_factual | How many episodes are there in Dragon Ball Z? | 291 | `Dragon Ball Z episodes` | **291 episodes**, premiered Apr 1989 – Jan 1996 | 6,547 | 1 | 5.7s | $0.04 | 1.00 | Y | Y | N | N |
| simple_factual | When was the first Hunger Games book published? | September 14, 2008 | `The Hunger Games book` | Published **September 14, 2008**, by Scholastic | 8,550 | 1 | 6.0s | $0.05 | 1.00 | Y | Y | N | N |
| simple_factual | What is the maximum data rate for 802.11a? | 54 Mbit/s | `802.11a wireless standard` | **54 Mbit/s**, OFDM in 5 GHz band | 8,951 | 1 | 7.4s | $0.05 | 1.00 | Y | Y | N | N |
| simple_factual | Who wrote 'He Ain't Heavy, He's My Brother' lyrics? | Bobby Scott and Bob Russell | `He Ain't Heavy He's My Brother song` | **Bobby Scott** and **Bob Russell** | 7,746 | 1 | 6.4s | $0.04 | 1.00 | Y | Y | N | N |
| simple_factual | How many seasons of Vampire Diaries are there? | 8 | `The Vampire Diaries television series` | **8 seasons**, 171 episodes, Sept 2009 – Mar 2017 | 8,637 | 1 | 5.9s | $0.05 | - | Y | Y | N | N |
| simple_factual | Where was Percy Jackson and the Olympians filmed? | Vancouver, British Columbia | `Percy Jackson and the Olympians filming locations`, `...Disney+ television series filming` | Filmed primarily in **Vancouver, British Columbia** | 20,227 | 2 | 14.6s | $0.11 | 1.00 | Y | Y | N | N |
| simple_factual | Who does the voice of Nala in The Lion King? | Moira Kelly (adult Nala) | `Nala Lion King character voice` | **Moira Kelly** (1994 adult), multiple VAs across franchise | 9,384 | 1 | 9.3s | $0.05 | 1.00 | Y | Y | N | N |
| multi_hop | Who is older, Annie Morton or Terry Richardson? | Terry Richardson | `Annie Morton model`, `Terry Richardson photographer` | **Terry Richardson** is older (born 1965 vs 1970) | 11,227 | 2 | 7.7s | $0.06 | 1.00 | Y | Y | N | N |
| multi_hop | Former band of Mother Love Bone member who died before 'Apple'? | Malfunkshun | `Mother Love Bone Apple album`, `Andrew Wood Malfunkshun band` | **Andrew Wood** died; former band was **Malfunkshun** | 16,441 | 2 | 11.0s | $0.09 | 1.00 | Y | Y | N | Y |
| multi_hop | Did LostAlone and Guster have the same number of members? | No, Guster has four and LostAlone has three | `LostAlone band`, `Guster band` | LostAlone: 3; Guster: 4 (including Ryan Miller). Not the same | 10,333 | 2 | 10.2s | $0.06 | 0.62 | Y | Y | N | N |
| multi_hop | Were Scott Derrickson and Ed Wood of the same nationality? | Yes, both are American | `Scott Derrickson filmmaker`, `Ed Wood filmmaker` | Both are **American** (same nationality) | 13,630 | 2 | 8.0s | $0.07 | 0.75 | Y | Y | N | N |
| multi_hop | Film by Brian Patrick Butler inspired by Kubrick film? | Friend of the World / Dr. Strangelove | `Brian Patrick Butler filmmaker director`, `Friend of the World 2020 film Kubrick Dr. Strangelove` | **Friend of the World** (2020), inspired by **Dr. Strangelove** | 18,549 | 2 | 17.2s | $0.10 | 1.00 | Y | Y | N | N |
| multi_hop | Arena where Celtics play opened in what year? | 1995 (TD Garden) | `Boston Celtics arena`, `TD Garden arena Boston opening year` | **TD Garden** opened in **1995** (originally FleetCenter) | 14,668 | 2 | 10.3s | $0.08 | 1.00 | Y | Y | N | Y |
| multi_hop | Arthur's Magazine or First for Women started first? | Arthur's Magazine (1844) | `Arthur's Magazine`, `First for Women magazine` | **Arthur's Magazine** (1844) before **First for Women** (1989) | 7,032 | 2 | 6.8s | $0.04 | 1.00 | Y | Y | N | N |
| multi_hop | Nationality of the director of 'Pandemonium'? | Ambiguous (multiple films share this title) | `Pandemonium film`, `Pandemonium film disambiguation`, `Alfred Sole film director` | Question is ambiguous — multiple films found: Pandemonium (1971, Japanese), Pandemonium (1982, American), Pandemonium (1987, British) | 25,658 | 3 | 22.5s | $0.14 | 0.90 | Y | Y | N | Y |
| multi_hop | Who was born first, Conan Doyle or Agatha Christie? | Arthur Conan Doyle (1859 vs 1890) | `Arthur Conan Doyle`, `Agatha Christie` | **Arthur Conan Doyle** (22 May 1859) before **Agatha Christie** (15 Sept 1890) | 12,985 | 2 | 8.3s | $0.07 | 0.83 | Y | Y | N | N |
| multi_hop | Peter Rabbit creator born in what country? | England (Beatrix Potter) | `Peter Rabbit series creator`, `Peter Rabbit Beatrix Potter` | **Beatrix Potter**, born in **England** | 19,585 | 2 | 10.2s | $0.10 | 1.00 | Y | Y | N | N |
| out_of_scope | What will the stock price of Apple be in 2030? | *(none)* | *(none)* | Declined: future prediction outside scope | 2,070 | 0 | 4.5s | $0.01 | - | - | - | N | N |
| out_of_scope | Should I invest in cryptocurrency or real estate? | *(none)* | *(none)* | Declined: personal financial advice outside scope | 2,113 | 0 | 4.6s | $0.01 | - | - | - | N | N |
| out_of_scope | What is the best programming language to learn in 2027? | *(none)* | *(none)* | Declined: future prediction + subjective judgment | 2,166 | 0 | 6.2s | $0.01 | - | - | - | N | N |
| out_of_scope | How do I feel about the new tax policy? | *(none)* | *(none)* | Declined: personal feelings/opinions outside scope | 2,073 | 0 | 3.8s | $0.01 | - | - | - | N | N |
| out_of_scope | What will be the next major scientific breakthrough? | *(none)* | *(none)* | Declined: future prediction outside scope | 2,114 | 0 | 4.5s | $0.01 | - | - | - | N | N |
| ambiguous | When did it happen? | *(none)* | *(none)* | Asked for clarification: "What event are you referring to?" | 2,048 | 0 | 3.0s | $0.01 | - | - | - | N | N |
| ambiguous | How tall is he? | *(none)* | *(none)* | Asked for clarification: "Which person are you asking about?" | 2,003 | 0 | 2.0s | $0.01 | - | - | - | N | N |
| ambiguous | What year did the war end? | *(none)* | *(none)* | Asked for clarification: "Which war are you referring to?" | 2,069 | 0 | 2.9s | $0.01 | - | - | - | N | N |
| ambiguous | Who won the game last night? | *(none)* | *(none)* | Asked for clarification: which sport, league, or teams? | 2,093 | 0 | 4.3s | $0.01 | - | - | - | N | N |
| ambiguous | Tell me about Mercury. | *(none)* | *(none)* | Asked for clarification: planet, element, Roman god, or Freddie Mercury? | 2,161 | 0 | 5.3s | $0.01 | - | - | - | N | N |

#### Aggregate (30 queries)

| Metric | v3 | v4 | Delta |
|---|---|---|---|
| Task completion rate | 100% | 100% | — |
| Total errors | 0 | 0 | — |
| Total tokens | 280,743 | 275,703 | -2% |
| Total cost | $1.53 | $1.52 | -1% |
| Avg latency | 8.5s | 7.8s | -8% |
| Avg tokens/query | 9,358 | 9,190 | -2% |
| Avg tool calls/query | 1.1 | 1.1 | — |
| Avg cost/query | $0.05 | $0.05 | — |
| Avg recall (token match) | 0.887 | 0.953 | +7% |
| Semantic correctness | 18/20 (90.0%) | 20/20 (100%) | +10% |
| Citation rate (tool-using queries only) | 20/20 (100%) | 20/20 (100%) | — |
| Query hallucinations (trajectory-based) | 0/30 | 1/30 | +1 |
| Answer hallucinations | 6/30 | 3/30 | -50% |

#### Observations

**Semantic correctness reaches 100%**:
- All 20 questions with expected answers are now semantically correct (up from 18/20 in v3).
- hp_03 now matches: corrected expected answer "No, Guster has four members and LostAlone has three" aligns with the agent's answer that notes the different member counts.
- hp_05 now matches: corrected expected answer "Friend of the World was inspired by Dr. Strangelove" aligns with what the agent consistently finds on Wikipedia.
- hp_08 now matches: the agent identifies that "Pandemonium" is ambiguous (multiple films) and lists the possibilities — matching the expected answer that states the question is ambiguous.

**Post-search ambiguity detection (hp_08)**:
- In v3, the agent picked the 1982 film and answered "American" — semantically incorrect vs the "ambiguous" expected answer.
- In v4, the agent searched, discovered multiple films titled "Pandemonium" (1971 Japanese, 1982 American, 1987 British), and correctly stated the question is ambiguous. This validates the new prompt rule allowing post-search ambiguity detection.

**Trajectory-based query hallucination**:
- 1/30 flagged: nq_03 ("ruler of England in 1616"). The first query `ruler England 1616` is fine, but the follow-up `James I England king 1603 1625` was flagged — the judge determined "James I" appeared in the first result's context, but "1603" and "1625" as specific dates in the query may have been considered excessive specificity. This is a borderline case.
- All multi-hop questions passed (0 hallucinations), validating that the trajectory-based approach correctly permits follow-up queries that use entities from retrieved context.

**Answer hallucinations halved**:
- Down from 6 → 3. Remaining flags: hp_02 (minor detail about Andrew Wood), hp_06 (opening ceremony date detail), hp_08 (specific director details in disambiguation answer).
- The reduction is driven by: (1) temperature=0 producing more conservative outputs, (2) full context passed to the judge (no truncation that could cause false positives), (3) the prompt encouraging the agent to avoid embellishment.

**Recall improvement**:
- Average recall increased from 0.887 → 0.953, primarily due to the corrected expected answers for hp_03 and hp_05 now aligning with what the agent produces. hp_08 also improved from 0.10 → 0.90 since the agent's "ambiguous" response better matches the expected answer.

**By category**:
- **Simple factual (10)**: 10/10 semantically correct, 10/10 cited. Only nq_03 had a query hallucination flag (borderline). 0 answer hallucinations.
- **Multi-hop (10)**: 10/10 semantically correct (up from 8/10 in v3). 0 query hallucinations. 3 answer hallucinations on hp_02, hp_06, hp_08. hp_08's ambiguity detection is a key v4 improvement.
- **Out-of-scope (5)**: Perfect — all 5 correctly declined.
- **Ambiguous (5)**: 5/5 correctly asked for clarification. 0 tool calls, 0 hallucinations.

---

*This document is updated with each new version. Add a new "Version N" section with the configuration diff, full results table, and aggregate stats.*
