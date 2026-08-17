"""What this product stores about people, why, and for how long.

The single list E13 is built on. Four things read it and nothing maintains a
copy:

  * ``core.privacy.deletion``  — what to do with a row when its author leaves
  * ``core.privacy.retention`` — what to delete on a timer
  * ``templates/legal/privacidade.html`` — the notice's purpose and retention
    tables, rendered from these rows rather than typed out beside them
  * ``core/tests/test_privacy_inventory.py`` — which fails when a model exists
    with no decision attached

That last one is the point. A privacy notice is only true on the day it is
written unless something forces it to keep up, and a list nobody is compelled
to update is the mechanism by which a compliant product quietly stops being one.

``purpose`` is pt-BR because it is rendered verbatim into a legal document that
Brazilians have to be able to read (S13-4). Everything else here is English,
like the rest of the codebase.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class Basis(StrEnum):
    """The lawful basis for a purpose. LGPD art. 7 defines ten; three apply.

    Decided in E13's brainstorm (plan decision D3) and confirmed by a lawyer
    before launch — this enum is engineering's record of the decision, not the
    legal opinion itself.
    """

    CONTRACT = "contrato"
    CONSENT = "consentimento"
    LEGITIMATE = "legitimo_interesse"

    @property
    def article(self) -> str:
        """The citation the notice prints next to each purpose."""
        return {
            Basis.CONTRACT: "art. 7º, V",
            Basis.CONSENT: "art. 7º, I",
            Basis.LEGITIMATE: "art. 7º, IX",
        }[self]

    @property
    def label(self) -> str:
        return {
            Basis.CONTRACT: "Execução de contrato",
            Basis.CONSENT: "Consentimento",
            Basis.LEGITIMATE: "Legítimo interesse",
        }[self]


class Disposal(StrEnum):
    """What happens to these rows when one member deletes their account (D1)."""

    #: Belongs to the household. Survives a member leaving; dies with the
    #: household when the last member goes, by the FK's own CASCADE.
    HOUSEHOLD = "household"
    #: The leaver's own rows are deleted, matched on ``created_by`` or ``user``.
    AUTHOR = "author"
    #: The database removes it when the user row goes. Nothing to do by hand.
    CASCADE = "cascade"
    #: Kept, with the user column set to NULL. Already how every ``created_by``
    #: behaves; listed explicitly for the rows we keep on purpose.
    ANONYMISE = "anonymise"
    #: The person themselves. Exactly one record carries this, and the deletion
    #: service does it last — a separate member rather than AUTHOR because
    #: "delete the rows this user wrote" and "delete this user" are different
    #: statements, and collapsing them would need a special case in the loop.
    SELF = "self"
    #: Holds no personal data at all — product configuration, reference tables.
    NONE = "none"


@dataclass(frozen=True)
class Record:
    """One model's privacy decision.

    ``timestamp_field`` and ``purge_filter`` exist only for ``retention_days``;
    ``subject_field`` only for ``Disposal.AUTHOR``. All three are on the record
    rather than in the services, because a service that knows something a model
    did not tell it is a second inventory.
    """

    label: str
    purpose: str
    basis: Basis | None
    disposal: Disposal
    retention_days: int | None = None
    timestamp_field: str = "created_at"
    #: Which column names the person, for AUTHOR rows. ``created_by`` on every
    #: ``AuthoredHouseholdModel``; ``core.Feedback`` calls it ``user``.
    subject_field: str = "created_by"
    purge_filter: dict = field(default_factory=dict)


#: Two years. Metering is what a bill is reconstructed from and what an abuse
#: claim is defended with, so it outlives the chat it measured.
_BILLING = 730

INVENTORY: tuple[Record, ...] = (
    # -- The ledger. The product itself, kept for as long as the account lives.
    Record(
        "finances.Entry",
        "Registrar seus gastos e receitas — o extrato que você veio usar.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "finances.Income",
        "Registrar sua renda, para projetar o mês.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "finances.Category",
        "Organizar os gastos por categoria.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "finances.PaymentMethod",
        "Saber em qual cartão ou conta cada gasto entrou, e em que mês ele fecha.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "finances.PaymentMethodClosingDay",
        "Guardar o dia de fechamento de um cartão num mês específico.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "finances.Budget",
        "Comparar o que foi gasto com o que foi planejado.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "finances.InstallmentPlan",
        "Acompanhar compras parceladas ao longo dos meses.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "finances.SystemicExpense",
        "Lembrar das despesas fixas que se repetem todo mês.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    # -- Jobs. The files themselves are deleted by a bucket lifecycle rule at 7
    #    days (D2a); these rows are the history of what happened.
    Record(
        "finances.ImportJob",
        "Mostrar o que aconteceu numa importação de CSV, inclusive as linhas "
        "que falharam — que trazem o texto original do seu arquivo.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
        # Only the abandoned ones. A finished import is the history page, and
        # docs/runbook.md says in as many words not to delete those.
        retention_days=180,
        purge_filter={"executed_at__isnull": True},
    ),
    Record(
        "finances.ExportJob",
        "Registrar quando você pediu uma cópia dos seus dados.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
        retention_days=180,
    ),
    # -- The assistant. Consent, and the shortest retention in the product.
    Record(
        "assistant.ChatMessage",
        "Manter o fio da conversa com o assistente. O conteúdo é enviado à "
        "OpenAI para ser processado.",
        Basis.CONSENT,
        Disposal.AUTHOR,
        retention_days=90,
    ),
    Record(
        "assistant.MemoryRule",
        "Lembrar suas correções — que 'cosmos' é mercado, por exemplo — para "
        "não errar a mesma categoria duas vezes.",
        Basis.CONSENT,
        Disposal.AUTHOR,
    ),
    Record(
        "assistant.MemoryEmbedding",
        "Encontrar a regra certa por semelhança de sentido. Vetores derivados "
        "das regras acima, calculados pela OpenAI.",
        Basis.CONSENT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "assistant.ReceiptDraft",
        "Guardar o que foi lido de um cupom até você confirmar ou descartar. "
        "A foto em si nunca é armazenada.",
        Basis.CONSENT,
        Disposal.AUTHOR,
        retention_days=90,
    ),
    # -- Metering. Legitimate interest: this is the bill and the abuse defence.
    Record(
        "assistant.UsageInteraction",
        "Contar quantos créditos cada uso do assistente custou.",
        Basis.LEGITIMATE,
        Disposal.ANONYMISE,
        retention_days=_BILLING,
    ),
    Record(
        "assistant.UsageRecord",
        "Registrar o custo real de cada chamada a um provedor de IA.",
        Basis.LEGITIMATE,
        Disposal.ANONYMISE,
        retention_days=_BILLING,
    ),
    # -- Tenancy and identity.
    Record(
        "core.CustomUser",
        "Sua conta: e-mail de acesso, senha (guardada como hash) e nome de exibição.",
        Basis.CONTRACT,
        Disposal.SELF,
    ),
    Record(
        "accounts.Household",
        "A casa cujas contas são compartilhadas.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "accounts.Membership",
        "Quem tem acesso a qual casa, e com qual papel.",
        Basis.CONTRACT,
        Disposal.CASCADE,
    ),
    Record(
        "accounts.Invitation",
        "Um convite pendente para alguém entrar na casa. Guarda o e-mail "
        "convidado até o convite ser aceito, cancelado ou vencer.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
        retention_days=180,
    ),
    Record(
        "accounts.OnboardingState",
        "Até onde a casa chegou na configuração inicial.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    # `core.PolicyAcceptance` and `core.Consent` are added here by Task 2, in
    # the same commit that creates them. Adding them now would make this file's
    # own completeness test fail on models that do not exist yet.
    Record(
        "account.EmailAddress",
        "Confirmar que o endereço de e-mail é seu.",
        Basis.CONTRACT,
        Disposal.CASCADE,
    ),
    Record(
        "account.EmailConfirmation",
        "Um link de confirmação de e-mail, de curta duração.",
        Basis.CONTRACT,
        Disposal.CASCADE,
    ),
    Record(
        "mfa.Authenticator",
        "A chave da sua verificação em duas etapas e os códigos de recuperação.",
        Basis.CONTRACT,
        Disposal.CASCADE,
    ),
    Record(
        "sessions.Session",
        "Manter você conectado entre uma página e outra.",
        Basis.CONTRACT,
        Disposal.ANONYMISE,
        # Zero days on `expire_date`: delete every session already expired.
        # This is `clearsessions` semantics, folded into the one job that runs.
        retention_days=0,
        timestamp_field="expire_date",
    ),
    # -- Security and abuse. Legitimate interest, and none of it is content.
    Record(
        "core.LoginAttempt",
        "Contar tentativas de login que falharam, para bloquear ataques de força bruta.",
        Basis.LEGITIMATE,
        Disposal.ANONYMISE,
        retention_days=30,
    ),
    Record(
        "core.AdminAccessLog",
        "Registrar quando um administrador abriu uma página que mostra dados de clientes.",
        Basis.LEGITIMATE,
        Disposal.ANONYMISE,
        retention_days=_BILLING,
    ),
    Record(
        "admin.LogEntry",
        "Registro do Django sobre o que um administrador alterou no painel.",
        Basis.LEGITIMATE,
        Disposal.CASCADE,
        retention_days=_BILLING,
        timestamp_field="action_time",
    ),
    # -- Product analytics. No user content, by construction.
    Record(
        "core.ProductEvent",
        "Contar passos do produto — cadastro, primeira foto, ativação. "
        "Nunca guarda o que você escreveu.",
        Basis.LEGITIMATE,
        Disposal.ANONYMISE,
        retention_days=_BILLING,
    ),
    Record(
        "core.Feedback",
        "O que você escreveu ao mandar um comentário sobre o produto.",
        Basis.LEGITIMATE,
        Disposal.AUTHOR,
        retention_days=_BILLING,
        # Not `created_by`: this model names the person `user`.
        subject_field="user",
    ),
    # -- Infrastructure and reference data. No personal data in any of these.
    Record(
        "core.TaskRun",
        "Fila de trabalhos em segundo plano. Guarda identificadores, nunca conteúdo.",
        None,
        Disposal.NONE,
        retention_days=90,
    ),
    Record(
        "accounts.Plan",
        "Os planos disponíveis. Igual para todo mundo.",
        None,
        Disposal.NONE,
    ),
    Record(
        "assistant.ModelPrice",
        "Tabela de preços dos modelos de IA. Igual para todo mundo.",
        None,
        Disposal.NONE,
    ),
    Record(
        "assistant.CreditPrice",
        "Quantos créditos custa cada tipo de uso. Igual para todo mundo.",
        None,
        Disposal.NONE,
    ),
    Record("auth.Group", "Grupos de permissão do Django.", None, Disposal.NONE),
    Record("auth.Permission", "Permissões do Django.", None, Disposal.NONE),
    Record(
        "contenttypes.ContentType",
        "Tabela interna do Django que nomeia os outros modelos.",
        None,
        Disposal.NONE,
    ),
)

_BY_LABEL = {record.label: record for record in INVENTORY}


def record_for(label: str) -> Record:
    """The decision for one model. ``KeyError`` when there is none — which is
    the same thing the completeness test says, only later."""
    return _BY_LABEL[label]


def purgeable() -> list[Record]:
    """The records the retention job walks."""
    return [record for record in INVENTORY if record.retention_days is not None]


def model_for(record: Record):
    """The Django model class a record names."""
    from django.apps import apps

    return apps.get_model(record.label)
