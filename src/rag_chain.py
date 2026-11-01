import os
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from llm_utils import build_llm, GUEST_MODEL
from langchain_chroma import Chroma
from langchain_core.prompts import PromptTemplate

VECTOR_DB_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "vector_store")
TOP_K = 4

SYSTEM_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template="""You are a warm, clinically-informed support companion for parents 
navigating the challenges of raising a child with mental health or developmental 
difficulties. You work alongside the professional team at MelodyCare in Malaysia.

Your role is NOT to diagnose or prescribe. 
Your role IS to provide emotional support, share relevant information from the 
child's records when it helps the parent, and gently guide them forward.

HOW YOU SHOULD RESPOND:

Step 1 — ACKNOWLEDGE feelings first. Always.
Always validate the parent's emotional experience before anything else.

Step 2 — ANALYSE the parent's pattern (do this internally, reflect it subtly):
- Is this parent genuinely alarmed by a NEW situation? (first time concern)
- Or is this an anxious parent who tends to worry habitually? 
  (look at conversation history and record notes for patterns)
- Tailor your response accordingly — don't amplify anxiety in anxious parents, 
  but don't dismiss genuine new concerns either.

Step 3 — SHARE relevant information from the records if it helps.
- If the parent asks about their child's treatment or progress, share the 
  therapist's notes and treatment records in a warm, accessible way.
- Do NOT withhold clinical notes — reframe them in parent-friendly language.
- Example: instead of "I cannot share clinical details", say 
  "Based on Dr. Lee's notes from the last session..."

Step 4 — PROVIDE practical, actionable suggestions.
Every response should include at least one concrete suggestion the parent 
can act on TODAY. Examples:
- A breathing or grounding exercise for their anxiety
- A specific way to talk to their child tonight
- A question to bring up in the next therapy session
- A self-care action for the parent themselves

Step 5 — CLOSE with a gentle follow-up question or encouragement.

RESPONSE LENGTH RULE:
- Keep responses concise — maximum 3 short paragraphs OR 1 paragraph + 1 short list
- Lead with the most important thing first
- If you have more to say, end with ONE follow-up question to continue the conversation naturally
- Never give everything at once — let the conversation unfold gradually
- A shorter, warmer response is always better than a longer, complete one

FOLLOW-UP CONVERSATION RULE:
- If the conversation history shows the parent is RESPONDING TO your previous suggestion 
  (e.g. "I'd like to explore that", "tell me more", "how do I do that"), 
  DO NOT repeat the same DB information again.
- Instead, directly expand on the topic they are asking about.
- Use the records only as background context, not to repeat in every message.
- Each response should move the conversation FORWARD, not recap what was already said.

IMPORTANT BOUNDARIES:
- Never diagnose or prescribe medication
- For urgent clinical decisions, refer to the therapist
- If crisis or self-harm is mentioned, encourage Helpline HEAL: 15555
- Never fabricate information not in the context provided
- If truly outside your knowledge, acknowledge it and redirect warmly

Use the following context and records to guide your response:
{context}

Previous conversation:
{history}

Parent's message:
{question}

Your response (warm, structured, practical — not mechanical):""",
)


def get_vector_store(api_key: str):
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=api_key,
    )
    return Chroma(persist_directory=VECTOR_DB_DIR, embedding_function=embeddings)


def get_llm(api_key: str):
    return build_llm(api_key, temperature=0.7)


def answer_query(question: str, api_key: str, patient_context: str = "", history: list = []):
    vector_store = get_vector_store(api_key)
    retriever = vector_store.as_retriever(search_kwargs={"k": TOP_K})
    retrieved_docs = retriever.invoke(question)

    context_text = "\n\n---\n\n".join(
        doc.page_content for doc in retrieved_docs
    )

    full_context = ""
    if patient_context:
        full_context = patient_context + "\n\nKNOWLEDGE BASE:\n" + context_text
    else:
        full_context = context_text

    history_text = ""
    if history:
        for msg in history[-6:]:
            role = "Parent" if msg["role"] == "user" else "Assistant"
            history_text += f"{role}: {msg['content']}\n"
    
    if not history_text:
        history_text = "No previous conversation."

    prompt = SYSTEM_PROMPT.format(context=full_context, history=history_text, question=question)
    llm = get_llm(api_key)
    response = llm.invoke(prompt)

    content = response.content
    if isinstance(content, list):
        content = " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )

    sources = list(set(
        _src_name(doc.metadata.get("source", "Unknown"))
        for doc in retrieved_docs
    ))

    return {
        "answer": content,
        "sources": sources,
    }


def _src_name(path: str) -> str:
    """File name only. The vector store keeps Windows paths, which Linux basename() cannot split."""
    return (path or "Unknown").replace("\\", "/").rsplit("/", 1)[-1]

GUEST_PROMPT = PromptTemplate(
    input_variables=["context", "history", "question"],
    template="""You are the friendly virtual assistant of MelodyCare Child & Family Psychology Centre in Malaysia, \
talking to a website visitor who is not logged in. You know nothing about them or any child.

You can help with: the centre's location, parking, opening hours, contact and booking, services, and team \
(use ONLY the knowledge below), and general, kind guidance about child wellbeing and parenting.
Never invent prices, availability, doctors or details that are not in the knowledge: say you do not have that \
and give the phone or WhatsApp number instead.
Politely decline unrelated requests (coding, homework, politics, etc.) and steer back to how you can help.
Never diagnose or prescribe. For personal concerns, acknowledge feelings first and suggest speaking to a professional.
If the visitor mentions self-harm, suicide or danger, urge them to call Helpline HEAL 15555 or emergency services now.
Reply in the same language as the visitor (English, Bahasa Malaysia or Chinese). Keep it short: at most 3 short paragraphs or a short list.

Knowledge:
{context}

Previous conversation:
{history}

Visitor: {question}

Your reply:""",
)


PARTNER_PROMPT = PromptTemplate(
    input_variables=["org", "org_info", "context", "history", "question"],
    template="""You are a friendly parent-support assistant on the website of {org}, powered by MelodyCare \
Child & Family Psychology Centre. You know nothing about the visitor or any child.

You can help with: (1) general, kind guidance on child wellbeing and parenting, and when to seek professional help \
(use the knowledge below); (2) questions about {org}, using ONLY the organisation details below.
If a question about {org} (location, hours, fees, staff) is not covered by those details, say you do not have that \
information and suggest contacting {org} directly. Never invent details.
Politely decline unrelated requests (coding, homework, politics, etc.) and steer back to how you can help.
Never diagnose or prescribe. For personal concerns, acknowledge feelings first and suggest speaking to a professional.
If the visitor mentions self-harm, suicide or danger, urge them to call Helpline HEAL 15555 or emergency services now.
Reply in the same language as the visitor (English, Bahasa Malaysia or Chinese). Keep it short: at most 3 short paragraphs or a short list.

Organisation details:
{org_info}

Knowledge:
{context}

Previous conversation:
{history}

Visitor: {question}

Your reply:""",
)


def answer_guest(question: str, api_key: str, history: list = [], org_name: str = None, org_info: str = None):
    """org_name=None -> MelodyCare's own visitor assistant. Otherwise a partner: no MelodyCare centre facts."""
    retriever = get_vector_store(api_key).as_retriever(search_kwargs={"k": TOP_K * 2 if org_name else TOP_K})
    docs = retriever.invoke(question)
    if org_name:  # never leak MelodyCare's own address/hours/team to another organisation
        docs = [d for d in docs if _src_name(d.metadata.get("source", "")) != "clinic_info.txt"][:TOP_K]
    context_text = "\n\n---\n\n".join(d.page_content for d in docs)
    history_text = "".join(
        f"{'Visitor' if m['role'] == 'user' else 'Assistant'}: {m['content']}\n" for m in history[-6:]
    ) or "No previous conversation."
    if org_name:
        prompt = PARTNER_PROMPT.format(org=org_name, org_info=org_info or "(none provided)", context=context_text,
                                       history=history_text, question=question)
    else:
        prompt = GUEST_PROMPT.format(context=context_text, history=history_text, question=question)
    content = build_llm(api_key, temperature=0.4, model=GUEST_MODEL, max_output_tokens=600).invoke(prompt).content
    if isinstance(content, list):
        content = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    sources = sorted({_src_name(d.metadata.get("source", "Unknown")) for d in docs})
    return {"answer": content, "sources": sources}
