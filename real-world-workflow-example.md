# Real-World Workflow: The New Memory Architecture in Action

This report demonstrates exactly how data moves through the new OLBrain memory architecture from start to finish, using a real-world e-commerce scenario via a WhatsApp agent.

---

## The Scenario
**User:** John (ID: `user_101`)
**Channel:** WhatsApp
**Goal:** Buying running shoes, then changing his mind the next day.

---

## Phase 1: The Initial Request (Monday)

**User texts:** *"Hi, I want to buy a pair of Nike running shoes. I wear size 10."*

### Stage 1: Evidence Capture
Before the AI even thinks, the system strictly records the raw reality of what just happened.
*   The system creates an **Evidence Record** in the database.
*   **Format Stored:**
    ```json
    {
      "evidence_id": "ev_001",
      "source": "whatsapp",
      "timestamp": 1728200000,
      "content": "Hi, I want to buy a pair of Nike running shoes. I wear size 10."
    }
    ```

### Stage 2: Gateway & Context Compiler
The Memory Gateway grabs the Current State for `user_101`. Since this is a new user, the state is empty. The Context Compiler hands the empty state and the new message to the LLM.

### Stage 3: LLM Proposal
The AI realizes it learned a fact. It **cannot** write this fact to the database. It can only propose it to the Gateway.
*   **Proposal Sent by AI:** 
    `Draft(predicate: "shoe_size", value: "10", evidence: ["ev_001"])`
    `Draft(predicate: "brand_preference", value: "Nike", evidence: ["ev_001"])`

### Stage 4: Claim Gate (The Bouncer)
The deterministic code takes over. It checks the **Predicate Policy Registry**.
*   *Rule check for "shoe_size":* Is this allowed? Yes. Cardinality? `SINGLE` (a person only has one shoe size at a time). 
*   *Result:* **ACCEPTED**.

### Stage 5: Durable Journal (The Vault)
The Gateway commits the accepted claims into the Durable Journal. This is an append-only ledger. It never overwrites.
*   **Format Stored in Journal:**
    ```json
    {
      "seq": 1,
      "kind": "claim",
      "subject_id": "user_101",
      "at_timestamp": 1728200005,
      "payload": {
        "claim_id": "clm_991",
        "predicate": "shoe_size",
        "value": "10",
        "provenance": ["ev_001"]
      }
    }
    ```

---

## Phase 2: The Change of Mind & Action (Tuesday)

**User texts:** *"Actually, change my size to 11. Also, go ahead and order them."*

### 1. Evidence Capture & LLM Proposal
*   New Evidence (`ev_002`) is recorded.
*   The Context Compiler tells the AI: *"Current State: shoe_size is 10."*
*   The AI reads the new message and proposes a correction: 
    `Draft(predicate: "shoe_size", value: "11", evidence: ["ev_002"])`

### 2. Claim Gate & Journal (Handling Conflicts)
The Gate checks the Policy Registry. Because `shoe_size` is `SINGLE`, the new claim clashes with the old one. 
*   **The deterministic rule:** The newer evidence supersedes the old one. 
*   The Journal writes the new claim, but it **does not delete** the old one. The timeline is preserved.
*   **Format Stored:**
    ```json
    {
      "seq": 2,
      "kind": "claim",
      "subject_id": "user_101",
      "payload": {
        "claim_id": "clm_992",
        "predicate": "shoe_size",
        "value": "11",
        "provenance": ["ev_002"]
      }
    }
    ```

### 3. Execution Memory (Tool Action)
The AI now executes the API to buy the shoes.
*   *Tool Call:* `buy_item(brand="Nike", size="11")` -> *Result:* `Success, Order #5555`.
*   This execution trace is saved as **Execution Evidence**.
*   The **Future Episode Generator** (the background worker) reads this trace and creates a **Narrative Memory**.
*   **Format Stored (Narrative Memory):**
    ```json
    {
      "episode_id": "ep_333",
      "subject_id": "user_101",
      "summary": "Agent successfully executed order #5555 for Nike shoes in size 11.",
      "tool_traces_referenced": ["trace_88"]
    }
    ```

---

## Phase 3: The Follow-Up (Wednesday)

**User texts:** *"Did you ship my shoes yet?"*

### 1. Context Compiler (Building the Snapshot)
Before the AI answers, the system builds the exact context it needs to see.
*   **Current State Projection:** It reads the Journal. It sees `shoe_size=10` at Seq 1, and `shoe_size=11` at Seq 2. It calculates the *Current* truth is **11**.
*   **Narrative Memory:** It retrieves the episode about Order #5555.

### 2. The Final Formatted Context Given to the AI
This is exactly what the AI sees, strictly separated so it cannot confuse background history with hard facts:

```text
[AUTHORITATIVE FACTS]
shoe_size: 11
brand_preference: Nike

[RECENT BACKGROUND NARRATIVE]
Tuesday: Agent successfully executed order #5555 for Nike shoes in size 11.

[NEW CHAT]
User: Did you ship my shoes yet?
```

### 3. The Resolution
The AI now perfectly understands what the user is talking about, knows the correct size, and knows the order number. It uses a tool `check_shipping(order_id="5555")` and replies accurately.

---

## Why this is vastly superior to the old system:
1. **No Hallucinations:** In the old system, the AI would try to rewrite a summary paragraph to change "10" to "11" and might accidentally delete the brand name in the process. Here, facts are isolated.
2. **Perfect Provenance:** If the CTO ever asks, *"Why does the system think John wears a size 11?"*, you can query `clm_992`, which points directly to `ev_002`. You can read the exact WhatsApp message that proved it.
3. **Execution Separation:** The fact that the agent ordered the shoes is stored as *Narrative background*, not an instruction. The AI won't accidentally read "order #5555" and try to buy the shoes a second time.
