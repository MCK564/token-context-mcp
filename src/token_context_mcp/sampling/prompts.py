"""Structured prompt templates with one-shot anchor and intent preservation."""
from __future__ import annotations

STRUCTURED_CONTEXT_PROMPT_TEMPLATE = """You are an expert deterministic code analysis engine assisting a software engineer.
Task: Deeply analyze the code snippet below strictly focusing on the User Intent.
Do not lose technical constraints, error handling details, or critical business rules.

[USER INTENT]
{user_raw_intent}

[TARGET SYMBOL ANCHORS]
{verified_symbol_names}

[ONE-SHOT EXAMPLE]
Input:
```python
class PaymentService:
    def refund(self, tx_id: str, amount: float):
        if amount <= 0:
            raise InvalidAmountException("Amount must be positive")
        return self.gateway.execute_refund(tx_id, amount)
```
Output:
{{"intent_alignment": "Validates refund amounts and delegates execution to gateway.", "analyzed_symbols": [{{"name": "PaymentService.refund", "responsibility": "Executes customer refund transactions with validation", "critical_constraints": ["amount must be greater than 0, otherwise raises InvalidAmountException"], "calls_external": ["gateway.execute_refund"]}}], "technical_caveats": ["Assumes self.gateway is initialized and handles its own network timeouts"]}}

[INPUT CONTEXT]
{structured_code_context}

Output must be valid JSON matching the exact schema above:"""

# Backward compatibility alias
COMPRESSION_PROMPT_TEMPLATE = STRUCTURED_CONTEXT_PROMPT_TEMPLATE
