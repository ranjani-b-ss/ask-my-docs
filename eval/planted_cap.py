"""Week 12 — planted-error set for the integrated-system judge.

Why it exists: of 70 natural outputs only 2 are UNGROUNDED (labels_cap_70.json), so agreement on the natural
set cannot show whether the judge can FIND an error. These are real packets (prose only; passages, tool
results and claim file untouched) with ONE minimal edit that plants a known error, plus control edits that
reword without changing any fact. The label is known by construction — but the edits are mine, so they test
the judge against errors I thought of; they are not a sample of the errors the system makes. Reported
separately and never blended into the natural agreement figure.

Error types:  stale  = a superseded or not-yet-in-force figure presented as current
              invent = a figure/threshold that appears in no passage or tool result
              contra = contradicts the passage or tool result it relies on
              fit    = a real rule applied to facts that do not satisfy it
              absent = a false claim that the wording says nothing on a point it does address
              ctrl   = reworded, every fact unchanged (must stay GROUNDED)
"""

# (id, base "version:claim", field, old, new, type)
EDITS = [
 ("P01","v2:CLM-2026-00602","summary","a compulsory deductible of INR 1,500 applies","a compulsory deductible of INR 1,000 applies","stale"),
 ("P02","v2:CLM-2026-00572","summary","a compulsory deductible of INR 3,000 applies","a compulsory deductible of INR 2,000 applies","stale"),
 ("P03","v2:CLM-2026-00584","summary","Endorsement 2 amends the reimbursement submission window to 30 days from discharge.","The reimbursement submission window remains 15 days from discharge.","stale"),
 ("P04","v2:CLM-2026-00496","summary","amended the specified illness waiting period to 12 months and the initial waiting period to 15 days","kept the specified illness waiting period at 24 months and the initial waiting period at 30 days","stale"),
 ("P05","v2:CLM-2026-00578","referral_reason","co-payment percentage of 10% applicable for insured persons aged 66 years and above","co-payment percentage of 20% applicable for insured persons aged 61 years and above","stale"),
 ("P06","v2:CLM-2026-00607","summary","specifies a 20% co-payment for insured persons aged 61 and above","specifies a 10% co-payment for insured persons aged 66 and above","stale"),
 ("P07","v2:CLM-2026-00437","summary","(INR 5,000 per day)","(INR 10,000 per day)","invent"),
 ("P08","v2:CLM-2026-00609","summary","is 1% of the sum insured per day (INR 5,000)","is 2% of the sum insured per day (INR 10,000)","stale"),
 ("P09","v2:CLM-2026-00479","summary","up to INR 2,00,000 until renewal","up to INR 5,00,000 until renewal","invent"),
 ("P10","v2:CLM-2026-00472","summary","specifying a 15-day decision window after receipt of the last document and a 30-day window where an investigation is warranted","specifying a 30-day decision window after receipt of the last document and a 45-day window where an investigation is warranted","stale"),
 ("P11","v2:CLM-2026-00461","summary","Endorsement 1 permits a maximum of two Nil Depreciation claims per policy year","Endorsement 1 permits a maximum of three Nil Depreciation claims per policy year","contra"),
 ("P12","v2:CLM-2026-00483","summary","provides that a second or subsequent claim results in the bonus reverting to nil","provides that a second claim halves the bonus and only a third claim reverts it to nil","contra"),
 ("P13","v2:CLM-2026-00502","summary","is 12 months per Endorsement 2","is 6 months per Endorsement 2","contra"),
 ("P14","v2:CLM-2026-00601","summary","the compulsory deductible is resolved as INR 1,000","the compulsory deductible is resolved as INR 1,500","contra"),
 ("P15","v2:CLM-2026-00553","summary","requires checking against Annexure A for qualifying procedures due to technological advancement","covers any procedure completed within 48 hours, and Annexure A need not be checked","contra"),
 ("P16","v2:CLM-2026-00442","why:0","telephone charges, and attendant comfort items","telephone charges, attendant comfort items and prescribed medicines","invent"),
 ("P17","v2:CLM-2026-00423","summary","governs policyholder cancellations and short-period scale refunds","provides a full premium refund on cancellation within 30 days","contra"),
 ("P18","v2:CLM-2026-00606","referral_reason","The adjuster should review the tyre damage limits and the 50% sub-limit applicable when tyres and the vehicle are damaged simultaneously.","The policy wording contains no limit on tyre replacement, so the adjuster should treat the tyres as fully recoverable.","absent"),
 ("P19","v2:CLM-2026-00567","why:0","unless the schedule provides worldwide cover","in all circumstances","contra"),
 ("P20","v2:CLM-2026-00514","summary","indicating intoxication against the exclusion clause","indicating a blood alcohol reading above the 0.03% threshold set in the exclusion clause","invent"),
 ("P21","v2:CLM-2026-00431","summary","requiring pre-authorisation at least 48 hours prior to admission","requiring pre-authorisation at least 24 hours prior to admission","contra"),
 ("P22","v2:CLM-2026-00561","summary","noting a compulsory deductible of INR 3,000 applies","noting a compulsory deductible of INR 1,500 applies","contra"),
 ("P23","v2:CLM-2026-00509","summary","The adjuster should examine the exclusion for treatment of alcoholism, drug or substance abuse","Because the member fell at home, the self-inflicted injury exclusion in clause 6 applies","fit"),
 ("P24","v2:CLM-2026-00461","referral_reason","and this is the third own damage claim","and this is the second own damage claim, so Nil Depreciation applies in full","fit"),
 # controls: wording changed, every fact kept
 ("C01","v2:CLM-2026-00602","summary","a compulsory deductible of INR 1,500 applies based on the vehicle's cubic capacity of 1400cc","the compulsory deductible is INR 1,500, which follows from the vehicle's 1400cc engine","ctrl"),
 ("C02","v2:CLM-2026-00437","summary","Room rent is capped at 1% of the sum insured per day for a normal ward (INR 5,000 per day)","For a normal ward the room rent limit is 1% of the sum insured a day, which is INR 5,000","ctrl"),
 ("C03","v2:CLM-2026-00584","summary","Endorsement 2 amends the reimbursement submission window to 30 days from discharge.","Under Endorsement 2 the reimbursement documents are due within 30 days of discharge.","ctrl"),
 ("C04","v2:CLM-2026-00472","summary","specifying a 15-day decision window after receipt of the last document and a 30-day window where an investigation is warranted","which sets 15 days to decide after the last document, extended to 30 days where an investigation is warranted","ctrl"),
 ("C05","v2:CLM-2026-00607","summary","specifies a 20% co-payment for insured persons aged 61 and above","provides for a 20% co-payment where the insured person is 61 or older","ctrl"),
 ("C06","v2:CLM-2026-00496","summary","amended the specified illness waiting period to 12 months and the initial waiting period to 15 days","changed the specified-illness waiting period to 12 months and the initial waiting period to 15 days","ctrl"),
]
