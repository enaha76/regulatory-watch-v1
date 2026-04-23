# Regulatory Watch: Architecture v2 Analysis
## 3 Critical Real-World Logic Flaws

This document outlines three significant architectural flaws identified in the current v2 pipeline design. These flaws stem from rigid assumptions that fail to capture the nuance of real-world regulatory compliance and international trade.

---

### 1. The Hardcoded Trade Flow (Geo Resolver)
**Location:** M4 (Significance) → `services/geo.py`

**The Assumption:**
The system assumes that the country publishing the rule (e.g., `cbp.gov` mapped to the US) is always the **Destination** of the trade flow, while the countries extracted by the LLM from the text are the **Origin**.

**How it Breaks in the Real World:**
Regulations control trade moving in two directions (Imports and Exports). If the US Office of Foreign Assets Control (OFAC) publishes an **export ban** on sending microchips to Russia, the trade flow is `outbound`. 
* **Real-world Origin:** US
* **Real-world Destination:** Russia

Because the `Geo Resolver` blindly hardcodes the regulator's jurisdiction as the destination, it will incorrectly log that the microchips are moving *inbound* from Russia to the US. It completely reverses the trade line.

**The Fix:**
The system must look at the `trade_flow_direction` (inbound vs. outbound) extracted by the LLM *before* assigning the regulator's country code to a bucket. If the flow is `outbound`, the regulator's jurisdiction becomes the Origin, not the Destination.

**Status:** ✅ Fixed — `resolve_destination_countries()` renamed to `resolve_jurisdiction()`. New `assign_trade_countries()` function routes the jurisdiction into the correct origin/destination bucket based on `trade_flow_direction`. See `app/services/geo.py` and `app/services/significance.py`.

---

### 2. The "Double Translation" Trap
**Location:** M4 (Significance) → M5 (Translation)

**The Assumption:**
The architecture assumes English is the ultimate universal middle-man for all processing and summarization.

**How it Breaks in the Real World:**
The v2 architecture correctly allows the LLM to natively read documents in any language (e.g., French). However, it instructs the LLM to *always* output the `compliance_summary` in English. In M5, if a user prefers French, it uses DeepL to translate that English summary back into French.

If a French regulator (`amf-france.org`) publishes a rule in French, and a French compliance officer wants to read it:
* French Text → LLM converts to English → DeepL translates English back to French.

This plays the "telephone game" with legal text. Crucial legal nuances are lost translating from FR to EN, and lost again translating from EN back to FR. It also wastes money on unnecessary DeepL API calls.

**The Fix:**
If the source `Document.language` matches the `User.preferred_lang`, bypass the English summary translation entirely. Ask the LLM to summarize it directly in the native language, or simply surface the original native text.

**Status:** 📝 Design constraint documented — M5 is not yet built. A code comment has been added in `app/services/significance.py` to ensure this is respected during M5 implementation.

---

### 3. The "Contextless Diff" Trap
**Location:** M3 (Change Detection) → M4 (Obligations LLM)

**The Assumption:**
The system assumes a unified text "diff" contains all the information needed to understand a new compliance obligation.

**How it Breaks in the Real World:**
In `services/significance.py`, when a document is updated (`diff_kind = modified`), the system truncates the text and **only sends the unified diff** to the LLM to save tokens. 

If a 100-page FDA guidance document is updated and the only change is in paragraph 42, the diff sent to the LLM might look like this:
```diff
- Compliance must be achieved by October 1st.
+ Compliance must be achieved by December 1st.
```
When the Obligations LLM is asked to extract the "Actor" and the "Action", it has absolutely no idea who the rule applies to. Is it for drug manufacturers? Medical device importers? Because the LLM *only* sees the isolated diff, it lacks the surrounding context of the document to know what rule actually changed, leading to hallucinations or empty obligation fields.

**The Fix:**
When sending a diff to the LLM, the system must also extract and send the "surrounding context" (e.g., the title of the section, or the paragraphs immediately above and below the change) so the LLM has enough legal context to understand who the new rule applies to.

**Status:** ✅ Fixed — `_build_user_prompt()` in `app/services/significance.py` now accepts and includes a `context_snippet` (the full document text, trimmed) alongside the diff for `modified` events. The `obligations.py` extractor also now prefers full document text over the bare diff.
