"""由 Core 执行的确定性决策授权规则。"""

from __future__ import annotations

from .decision_models import DecisionActionType, PolicyVerdictType
from .decision_schemas import ManagerDecisionProposal, PolicyVerdict


class DecisionPolicyService:
    """模型只能提出动作；这里给出最终 allow/confirm/deny 裁定。"""

    _confirmation_actions = {
        DecisionActionType.CONFIRM_PLAN,
        DecisionActionType.SUBMIT_PLAN,
        DecisionActionType.CANCEL_PLAN,
        DecisionActionType.CANCEL_RUN,
        DecisionActionType.CREATE_CASE_DRAFT,
        DecisionActionType.CREATE_SAMPLE_DRAFT,
        DecisionActionType.CREATE_TARGET_DRAFT,
    }

    def evaluate(self, proposal: ManagerDecisionProposal) -> PolicyVerdict:
        action = proposal.selected_action.action_type
        if proposal.schema_version != "agentrig.manager-decision.v1":
            return PolicyVerdict(
                verdict=PolicyVerdictType.DENY,
                reasons=["unsupported decision schema version"],
            )
        if action in self._confirmation_actions:
            return PolicyVerdict(
                verdict=PolicyVerdictType.REQUIRE_CONFIRMATION,
                reasons=["this action changes confirmed or shared business state"],
            )
        return PolicyVerdict(verdict=PolicyVerdictType.ALLOW)
