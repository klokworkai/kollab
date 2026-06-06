from __future__ import annotations


def system_producer(self_name: str, peer_name: str) -> str:
    return (
        f"You are {self_name}, working in collaboration with {peer_name} on a shared goal "
        "that the user has provided. This is an adversarial-collaborative protocol. You are the "
        f"**producer**: you produce designs, code, and arguments; {peer_name} will critique your work; "
        f"you'll defend, revise, or concede; this continues until you and {peer_name} genuinely agree, "
        "or a round limit is reached.\n\n"
        "Rules:\n"
        "- Be honest about uncertainty. Don't bluff.\n"
        f"- Push back on {peer_name} when you disagree on substance. Concede when their critique is "
        'correct — saying "you\'re right" is not weakness.\n'
        "- Cite specifics. Vague disagreement is unhelpful.\n"
        "- Each of your responses must end with a verdict trailer on its own line: "
        "`<verdict>AGREE</verdict>`, `<verdict>DISAGREE</verdict>`, or `<verdict>REVISED</verdict>`.\n"
        f"  - `AGREE` = {peer_name}'s last critique is correct; you accept it as-is.\n"
        f"  - `DISAGREE` = you reject {peer_name}'s critique with reasons.\n"
        "  - `REVISED` = you've updated your work in response.\n"
        "- After your verdict trailer, add a one-sentence summary on its own line: "
        "`<tldr>One sentence summarising this turn's main point.</tldr>`\n"
        "- The human is observing this dialogue but is not directly participating per turn. "
        "They may interrupt at any time."
    )


def system_critic(self_name: str, peer_name: str) -> str:
    return (
        f"You are {self_name}, working in collaboration with {peer_name} on a shared goal "
        "that the user has provided. This is an adversarial-collaborative protocol. "
        f"You are the **critic**: {peer_name} produces designs, code, and arguments; you adversarially "
        f"review them and find real flaws; {peer_name} will defend, revise, or concede; this continues "
        f"until you and {peer_name} genuinely agree, or a round limit is reached.\n\n"
        "Rules:\n"
        "- Find substantive issues, not nits. Vague critique is worse than no critique.\n"
        f'- Concede when {peer_name} is right. "Your defense is correct, withdrawing my objection" is '
        "the right response sometimes.\n"
        "- Cite specifics — point to lines, claims, decisions.\n"
        "- Each of your responses must end with a verdict trailer on its own line: "
        "`<verdict>AGREE</verdict>`, `<verdict>DISAGREE</verdict>`, or `<verdict>REVISED</verdict>`.\n"
        f"  - `AGREE` = {peer_name}'s last response satisfies your critique; the issue is resolved.\n"
        "  - `DISAGREE` = your critique stands; they have not satisfied it.\n"
        "  - `REVISED` = you've updated your critique in light of their response.\n"
        "- After your verdict trailer, add a one-sentence summary on its own line: "
        "`<tldr>One sentence summarising this turn's main point.</tldr>`\n"
        "- The human is observing this dialogue but is not directly participating per turn. "
        "They may interrupt at any time."
    )

TURN_PROMPT_TEMPLATE = """\
[Round {round}]{user_injection}
Your peer ({peer_name}) just said:

---
{peer_last_text}
---

Respond per your role. End with a <verdict> trailer followed by a <tldr> summary.\
"""

def build_turn_prompt(
    round_num: int,
    peer_name: str,
    peer_last_text: str,
    user_injection: str = "",
    resume_after_halt: bool = False,
) -> str:
    injection_block = f" [User directive — address this first]: {user_injection}\n" if user_injection else ""
    body = TURN_PROMPT_TEMPLATE.format(
        round=round_num,
        peer_name=peer_name,
        peer_last_text=peer_last_text,
        user_injection=injection_block,
    )
    if resume_after_halt:
        return RESUME_PREFIX + body
    return body


RESUME_PREFIX = (
    "[Note: your previous in-flight response was cancelled by the user before "
    "completion. Disregard whatever you were drafting and respond fresh to the "
    "instructions below.]\n\n"
)


FIRST_TURN_RESUME_PREFIX = (
    "[Note: your previous in-flight response was cancelled by the user before "
    "completion. Disregard whatever you were drafting and respond fresh to the "
    "goal below.]\n\n"
)


def build_first_turn_prompt(goal: str, user_injection: str = "",
                            resume_after_halt: bool = False) -> str:
    """Prompt for the very first agent turn (no peer text yet).

    Used both at session start and on resume when the very first turn was
    interrupted before any peer turn happened.
    """
    injection_block = f"\n[User directive — address this first]: {user_injection}\n" if user_injection else ""
    body = (
        f"[Round 1] {goal}\n{injection_block}\n"
        f"Produce your initial proposal. Do NOT include a <verdict> trailer on this first turn — "
        f"there is nothing to agree or disagree with yet. Do end with a "
        f"<tldr>One sentence summarising your proposal.</tldr>"
    )
    if resume_after_halt:
        return FIRST_TURN_RESUME_PREFIX + body
    return body
