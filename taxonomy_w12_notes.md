# Open-coding notes — integrated system (Week 12)

**Method.** I read all 72 runs (36 claims × first run `triage-v1`, final run `triage-v2`) as compact traces — route, queries, citations, numbers, referral text, summary, guard hits, tool failures — **without the assertion verdicts**, and wrote one observation sentence for each *before* any mode existed. Sentences describe what happened; they do not diagnose. This is a census, not a sample: every run of the eval set. One reader (me); not independent. Trace ids are in `traces/capstone_traces.jsonl`.

## First run (v1)

- **CLM-2026-00418** `cap_9fd6b2e632ce` — First search was sent with the query as {"type": "permanent exclusion"} and rejected; a referral attempt was blocked; the run stopped on the 30,000-token budget at 31,871 tokens with no citations, no facts and no summary.
- **CLM-2026-00423** `cap_698b9e5b650e` — Cites only the "3. Free look period" clause of the definitions document, while the referral text sends the adjuster to "Clause 4 Cancellation" of that document.
- **CLM-2026-00431** `cap_a7ba5eb3cb8b` — Cites the base cashless clause 7 and a definitions clause; no endorsement is cited although the summary quotes room rent and sum insured.
- **CLM-2026-00437** `cap_ad11de1e3bc1` — First search rejected ({"type": "room rent"}), second accepted; cites 1.1 Room rent limits and states 1% of sum insured, INR 5,000 a day.
- **CLM-2026-00442** `cap_ba5ef6326aac` — Summary, referral reason and one "why" field are all replaced by "[withheld: this text stated an outcome]"; the adjuster gets facts, two clause-6 citations and numbers, and no prose.
- **CLM-2026-00455** `cap_c36f932a4f18` — First search rejected; cites both the endorsement's Nil Depreciation clause and the base clause 2.1 it amends; one "why" replaced after containing the word "payable".
- **CLM-2026-00461** `cap_e5ffb3bd8466` — First search rejected; cites the endorsement's Nil Depreciation clause only; summary says the third claim of the year exceeds the two-claim limit.
- **CLM-2026-00468** `cap_7a5dfb3ca177` — Searched "ambulance" and "road ambulance"; hit the token budget at lap 10; empty packet — no facts, no citations, forced referral.
- **CLM-2026-00472** `cap_42d4ed97ebc5` — Cites the endorsement's settlement-timeline clause and the base clause 3 it amends; deductible shown as unresolved (no engine size) with nothing in the referral saying so.
- **CLM-2026-00479** `cap_75f3249512a1` — First search rejected; cites the endorsement's newborn clause twice and the base maternity clause; two "why" fields replaced after containing "covered".
- **CLM-2026-00483** `cap_68907ac851af` — First search rejected; cites the endorsement's No Claim Bonus clause; deductible unresolved (no engine size) and not mentioned in the referral.
- **CLM-2026-00491** `cap_1ecfb8b16bd0` — First search rejected; cites base clause 4 and the endorsement's constructive-total-loss clause while the summary says the endorsement amends intimation to 72 hours — a fact that sits under a different heading inside the same chunk; deductible unresolved and unmentioned.
- **CLM-2026-00496** `cap_318a4c53e81c` — Cites the base day-care clause and the endorsement's waiting-period clause; the summary compares 24 months with 12 months as the question asked.
- **CLM-2026-00502** `cap_0a4c8f49435c` — First search rejected, two more searches made; cites base clauses 3 and 4.1 and the endorsement's waiting-period clause; summary states a 12-month waiting period for cataract.
- **CLM-2026-00509** `cap_8b7b49878fd3` — Five searches (liquor, intoxicating, alcohol, drugs, 'what is not covered') used 35,732 tokens; budget stop; empty packet with a forced referral.
- **CLM-2026-00514** `cap_6dd5ae2f3adb` — First search rejected; cites base clause 3 twice; summary and referral reason both replaced by the withheld marker; deductible 1,500 for a 1,500 cc car.
- **CLM-2026-00521** `cap_0eb4304212f9` — Generic question 'Tell me about the policy'; first search rejected; cites base clause 1; deductible unresolved and not flagged; one "why" replaced.
- **CLM-2026-00526** `cap_81058ba6535b` — Generic question 'What does this policy cover?'; first search rejected, three more searches; budget stop at 34,143 tokens; empty packet.
- **CLM-2026-00533** `cap_de8a9935c1cd` — Three searches ('supersedes' twice) and a further search issued after the referral had already been made; budget stop; empty packet.
- **CLM-2026-00541** `cap_acafa0671116` — Searched 'subsumed items' and 'Annexure C'; cites base clause 6; the summary contains the literal text [REDACTED] where the redactor removed words after the verb 'address'; a search ran after the referral.
- **CLM-2026-00548** `cap_8fd1eda5eca1` — Cites the endorsement's modern-treatments clause; summary replaced by the withheld marker after containing 'covered'.
- **CLM-2026-00553** `cap_2ac6178d9be4` — First search rejected; cites the day-care clause; summary quotes the 24-hour criterion.
- **CLM-2026-00561** `cap_abaea0799f3f` — Tyre question; cites base clause 3 twice and the endorsement's Nil Depreciation clause; summary and referral reason replaced; five guard hits; deductible 3,000 with a 900,000 limit.
- **CLM-2026-00567** `cap_bbd88af63295` — Cites base clause 6 twice for treatment outside India; one "why" flagged by the guard; summary intact.
- **CLM-2026-00572** `cap_bca8dcc5ba36` — Called get_limits first and a premature referral was blocked; first search rejected; cites the endorsement's deductible clause and the base clause 2.2 it replaces; states 3,000 from the endorsement.
- **CLM-2026-00578** `cap_4b0c9d736ca1` — Cites the base co-payment clause and the endorsement's amendment to it; a fact line and the summary are replaced after containing 'Admissible'.
- **CLM-2026-00584** `cap_81af890ed07a` — Cites the endorsement's co-payment clause, while the summary gives a 30-day reimbursement window that sits under the next heading ('Amendment to Clause 8') inside the same chunk.
- **CLM-2026-00601** `cap_cf442790a57f` — get_limits called before search and a premature referral was blocked; cites base clause 2.2; deductible 1,000 — the pre-endorsement figure for a loss the day before.
- **CLM-2026-00602** `cap_3e24c30439a3` — First search rejected; cites the endorsement's clause 2.2 and the base clause 2.2 together; deductible 1,500; the summary names only the endorsement.
- **CLM-2026-00603** `cap_f9caaa40d16f` — Three-call route; in force false; no wording and no numbers; the reason gives the window end and the loss date.
- **CLM-2026-00604** `cap_a69f0d026809` — Three-call route; in force false; no wording and no numbers; the reason gives the window start and the loss date.
- **CLM-2026-00605** `cap_7bbd738c0f00` — First search rejected; cites base clauses 3 and 1; deductible 1,500; none of the fact lines I read contains a name, address or injury.
- **CLM-2026-00606** `cap_c7943b5a8e3f` — First search rejected; cites base clause 3 and the endorsement's Nil Depreciation clause; referral reason replaced after 'covered'; 50% tyre sub-limit listed in the numbers.
- **CLM-2026-00607** `cap_6d27abd3b12d` — Cites the base co-payment clause; states 20% for age 63 on the day before the endorsement; the summary contains [REDACTED].
- **CLM-2026-00608** `cap_1ba740483b7f` — get_limits before search; cites the base co-payment clause and the endorsement's amendment; co-payment null; two refer_to_adjuster calls both executed and two referral records exist for the one claim.
- **CLM-2026-00609** `cap_c8b89b1657a7` — First search rejected; cites 1.1 Room rent limits and the hospitalisation benefit; one "why" replaced after 'covered'.

## Final run (v2)

- **CLM-2026-00418** `cap_288af0834d12` — Cites base clause 6; summary and one "why" replaced by the withheld marker; no rejected calls.
- **CLM-2026-00423** `cap_06204240eb25` — Same as the first run: cites "3. Free look period" while the referral text points the adjuster to "4. Cancellation".
- **CLM-2026-00431** `cap_410b83799285` — Cites only the definitions clause; the base cashless clause 7 was dropped as amended and the endorsement's clause is not cited, yet the summary describes cashless provisions and a 48-hour pre-authorisation requirement.
- **CLM-2026-00437** `cap_cc47feba33ca` — Cites 1.1 Room rent limits; states 1% of sum insured, 5,000 a day, proportionate deduction; no failed calls.
- **CLM-2026-00442** `cap_5768c90e38da` — Cites base clause 6 twice; referral reason replaced after 'are excluded'; a "why" replaced after 'payable'.
- **CLM-2026-00455** `cap_0dc24564a1e3` — Cites the endorsement's Nil Depreciation clause only; summary replaced after 'payable'.
- **CLM-2026-00461** `cap_928bece548b1` — Cites the endorsement's Nil Depreciation clause; summary says the third claim exceeds the two-claim limit; one "why" flagged.
- **CLM-2026-00468** `cap_35f4fbc3c0b5` — One search for 'ambulance'; twelve laps without a Final Answer; stopped on the iteration limit; empty packet.
- **CLM-2026-00472** `cap_6dcff180a2ea` — Cites only the endorsement's settlement-timeline clause; deductible shown as needing a vehicle size, now flagged in the referral.
- **CLM-2026-00479** `cap_ffee6e89feb4` — Cites the endorsement's newborn clause twice; a 'why' flagged for 'covered'; summary gives the 30-day intimation against 37 days.
- **CLM-2026-00483** `cap_9765f1819b63` — Cites the endorsement's No Claim Bonus clause; deductible needs a vehicle size and is flagged.
- **CLM-2026-00491** `cap_d01f24346ba7` — Two searches ('intimate', 'notice'); a premature referral blocked; stopped on the token budget at 31,709; empty packet.
- **CLM-2026-00496** `cap_d1062cc74ef3` — Cites the endorsement's waiting-period clause and two base chunks (4.1 and the day-care chunk that also holds clause 4); summary compares 24 months with the endorsement as asked.
- **CLM-2026-00502** `cap_f7a25de9adfb` — Cites the endorsement's waiting-period clause and the day-care chunk; summary states 12 months for cataract; no failed calls.
- **CLM-2026-00509** `cap_3175e0307732` — Three searches; cites base clause 6 twice; referral reason replaced after 'covered'.
- **CLM-2026-00514** `cap_9902b4fca139` — Cites base clause 3 twice; referral reason replaced; summary names the police report and the 1,500 deductible.
- **CLM-2026-00521** `cap_b47b48a26a2b` — Cites 'what is covered', 'what is not covered' and the No Claim Bonus clause for a generic question; deductible needs a vehicle size, flagged.
- **CLM-2026-00526** `cap_dfecd0c899a9` — Cites the hospitalisation benefit; the base cashless clause 7 was dropped as amended; the summary still mentions 48-hour pre-authorisation rules.
- **CLM-2026-00533** `cap_caabea97709e` — Searched 'co-payment' for a question about which document supersedes; cites the endorsement's co-payment clause (base copy dropped); summary says the endorsement supersedes the base on co-payment and room rent.
- **CLM-2026-00541** `cap_d666d6e5726c` — Two searches; cites 1.1 Room rent limits and the hospitalisation benefit; the referral says the wording does not mention whether cradle charges, comb or room fresheners are subsumed.
- **CLM-2026-00548** `cap_c38987bf6042` — A premature referral blocked; cites the endorsement's modern-treatments clause; summary gives a 50% cap and asks the adjuster to check the listed procedures; a "why" flagged.
- **CLM-2026-00553** `cap_c110bc4ea621` — Cites the day-care clause; the referral asks the adjuster to confirm whether the procedure is listed in the annexure.
- **CLM-2026-00561** `cap_de961a822f0e` — Two searches; cites base clause 3 twice and the endorsement's No Claim Bonus clause for a tyre question; one "why" flagged.
- **CLM-2026-00567** `cap_a96fb2efed08` — Cites base clause 6 twice; ten laps; the summary says the outside-India exclusion "applies to these facts for the adjuster to weigh"; a "why" flagged.
- **CLM-2026-00572** `cap_c7f72ab8bbd5` — get_limits first, premature referral blocked; cites only the endorsement's deductible clause; states 3,000 for 1,800 cc.
- **CLM-2026-00578** `cap_d6befc4977ac` — Cites only the endorsement's co-payment clause; a fact line, the summary and a "why" replaced after 'Admissible'.
- **CLM-2026-00584** `cap_06e1e9611841` — Cites the endorsement's co-payment clause, while the summary says the endorsement extends the reimbursement window to 30 days — text under the next heading in the same chunk.
- **CLM-2026-00601** `cap_fde18a29a98e` — get_limits first, premature referral blocked; cites base clause 2.2; deductible 1,000 and the same clause named in the summary.
- **CLM-2026-00602** `cap_3ecd0e89505f` — get_limits first, premature referral blocked; cites only the endorsement's clause 2.2; the base clause 2.2 was dropped; deductible 1,500.
- **CLM-2026-00603** `cap_072f4dca3312` — Three-call route; in force false; the referral reason states the window end and the loss date.
- **CLM-2026-00604** `cap_b8d9340480d1` — Three-call route; in force false; the referral reason states the window start and the loss date.
- **CLM-2026-00605** `cap_3eb2219c7d3c` — Cites base clauses 1 and 3; deductible 1,500; the fact lines contain no name, address or injury.
- **CLM-2026-00606** `cap_3899a978f776` — Cites only the endorsement's chunk labelled 'No Claim Bonus protection'; that chunk's second section states the 50% tyre limit remains in force, which the summary then repeats.
- **CLM-2026-00607** `cap_dae84f057bdc` — Cites the base co-payment clause; summary says 20% applies at age 63.
- **CLM-2026-00608** `cap_c9d6e02bc855` — Cites the endorsement's co-payment clause; summary says the age threshold is raised to 66; co-payment null.
- **CLM-2026-00609** `cap_206e20a66937` — Cites 1.1 Room rent limits; summary gives 5,000 a day against a 9,000 room.

## Final system (v3b: `triage-v3`, structured chunking, exclusions gate, parser fix) — added 2026-10-16

Same method: all 36 runs rendered without assertion verdicts and read; one sentence each. Honest caveat: these sentences were written *after* I had already read the v1/v2 modes, and I looked up the referral flags and chunk text for four runs (00423, 00496, 00584, 00606) before writing, so this section is not as blind as the first one. Trace ids are in `traces/capstone_traces.jsonl` (`submitted_by` = `capstone-eval-v3b`).

- **CLM-2026-00418** `cap_4e1ff38fb344` — One search ("What is not covered permanent exclusions"), one clause cited; summary, one fact and one "why" all replaced by the withheld marker after containing "covered" ("covered for 3 years" in a fact).
- **CLM-2026-00423** `cap_739ba18da889` — Cites "3. Free look period" and the exclusions section; the referral sends the adjuster to "Clause 4 Cancellation", which sits in the same chunk under a later heading; summary withheld after "covered"; a referral attempt was blocked first.
- **CLM-2026-00431** `cap_01533fa123ee` — Cites the exclusions section and a definitions clause, no cashless endorsement clause; the endorsement's cashless clause was dropped as superseded; co-payment shown as needing an age, nothing in the referral says so.
- **CLM-2026-00437** `cap_42b4e91752a0` — Cites 1.1 Room rent limits and states 1% of sum insured, INR 5,000 a day; one blocked referral then a second search; co-payment needs an age, unflagged.
- **CLM-2026-00442** `cap_662208401989` — Cites the exclusions section twice; referral reason replaced by the withheld marker, a "why" too; summary intact.
- **CLM-2026-00455** `cap_152087888998` — Cites the Nil Depreciation endorsement clause; summary withheld after "payable"; one superseded base clause dropped.
- **CLM-2026-00461** `cap_e9c5e33c4b85` — Cites the Nil Depreciation endorsement clause only; summary says third claim of the year exceeds the limit; clean.
- **CLM-2026-00468** `cap_045513f9f157` — Four searches ("road ambulance", "ambulance", "What is not covered", "transport"); budget stop at lap 9; empty packet with forced referral after one blocked referral.
- **CLM-2026-00472** `cap_6caec616781a` — Cites the settlement-timeline endorsement clause and the exclusions section; base clause dropped as superseded; deductible shown as needing engine size, and the referral record carries an `unresolved:deductible` flag.
- **CLM-2026-00479** `cap_320964f797f0` — Three searches including two with "What is not covered"; budget stop at 36,580 tokens; empty packet with forced referral.
- **CLM-2026-00483** `cap_8531a73dae63` — Two searches, one blocked referral; budget stop at 32,136 tokens; empty packet; deductible needs engine size and the referral carries the unresolved flag.
- **CLM-2026-00491** `cap_b4050c3f8dcd` — Cites base clause 4 and the exclusions section; the referral and summary say 48 hours — the base figure — though the question is about the amended intimation period; deductible unresolved and flagged.
- **CLM-2026-00496** `cap_2f07087bd0c7` — Cites the waiting-period endorsement and "4.1 Accident exception"; the summary's 24-month figure sits under heading 4.2 in the same chunk; co-payment not unresolved here (age on file).
- **CLM-2026-00502** `cap_39f232bb6d8d` — Three searches; budget stop at 32,395 tokens; empty packet with forced referral after a blocked referral.
- **CLM-2026-00509** `cap_b0d808970cec` — One search naming alcohol and "What is not covered"; cites the exclusions section twice; summary withheld after "covered"; a "why" too.
- **CLM-2026-00514** `cap_34c6f3f1ee66` — One search; cites the motor exclusions section twice; summary and referral reason both withheld after "covered".
- **CLM-2026-00521** `cap_8af9af985a4c` — Generic question; one search "What is not covered"; cites "1. What is covered", the exclusions section and the NCB clause; deductible needs engine size, flagged.
- **CLM-2026-00526** `cap_5ecda49e12c2` — Generic question; cites the hospitalisation benefit and the exclusions section; clean apart from an unflagged co-payment.
- **CLM-2026-00533** `cap_dedb8b5dd8ae` — Three searches; budget stop at 36,131 tokens; empty packet with forced referral after a blocked referral.
- **CLM-2026-00541** `cap_0d45c7a3cab6` — Cites the exclusions section twice and the hospitalisation benefit; summary withheld; the referral does not claim the wording is silent.
- **CLM-2026-00548** `cap_6734ac872211` — Two searches; budget stop at 32,680 tokens; empty packet after a blocked referral.
- **CLM-2026-00553** `cap_d4b21308cba3` — Cites the day-care clause; summary withheld after "payable".
- **CLM-2026-00561** `cap_4a7487eb3a07` — Cites the exclusions section twice and the NCB clause; summary states tyre damage alone is excluded unless the vehicle is damaged too; the guard hit only the "why" fields; summary intact.
- **CLM-2026-00567** `cap_16f81e9e28df` — Cites the exclusions section twice; summary intact; two "why" fields flagged.
- **CLM-2026-00572** `cap_8a8f3db72af9` — Cites the compulsory-deductible endorsement clause; deductible 3,000 for an 1800 cc car; clean.
- **CLM-2026-00578** `cap_d4c196813418` — Cites the co-payment endorsement clause and the exclusions section; summary, a fact and a "why" withheld ("covered", "admissible").
- **CLM-2026-00584** `cap_fb53ff4f85f2` — Cites the co-payment endorsement clause (the 30-day window is under clause 5 of the same chunk) and base clause 8 that the endorsement amends; summary gives the 30-day figure correctly.
- **CLM-2026-00601** `cap_cbdacc3cbf93` — Cites base clause 2.2 and the exclusions section; deductible 1,000; clean.
- **CLM-2026-00602** `cap_43b78a20d603` — Cites the endorsement's deductible clause only; deductible 1,500; one blocked referral first; clean.
- **CLM-2026-00603** `cap_355b17da5fd5` — Not in force; four laps, no search; referral states the in-force window ended; clean.
- **CLM-2026-00604** `cap_44217d20e131` — Not in force; four laps; clean.
- **CLM-2026-00605** `cap_a52d612313bd` — The PII claim; one search; cites "1. What is covered"; deductible 1,500; clean.
- **CLM-2026-00606** `cap_32a5bf64256b` — Cites the motor exclusions section (which holds the 50% tyre limit) and the NCB endorsement clause; referral reason withheld after "covered"; the 50% fact has a correctly labelled citation here.
- **CLM-2026-00607** `cap_a0c6cc129bc7` — Cites the base co-payment clause 9 with age 63; clean.
- **CLM-2026-00608** `cap_b52b621d6f83` — Cites the co-payment endorsement clause; base clause dropped as superseded; clean.
- **CLM-2026-00609** `cap_b9690661c316` — Cites the exclusions section and 1.1 Room rent limits; 35,134 tokens, just over budget but a Final Answer arrived; clean.
