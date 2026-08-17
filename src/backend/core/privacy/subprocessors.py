"""Every third party that receives personal data, and what it receives.

S13-6. Kept in code rather than only in a document because the privacy notice
renders it and `docs/architecture/data-inventory.md` is checked against it — one
list, three readers, no chance of the notice naming a vendor the product does
not use or missing one it does.

Every entry here was verified against the codebase at 65a1c7d. Adding a vendor
means adding a row here *and* saying so in the notice, which the tests enforce.
"""

from dataclasses import dataclass
from enum import StrEnum


class Country(StrEnum):
    BR = "Brasil"
    US = "Estados Unidos"


@dataclass(frozen=True)
class SubProcessor:
    name: str
    role: str
    receives: str
    country: Country
    url: str


SUBPROCESSORS: tuple[SubProcessor, ...] = (
    SubProcessor(
        name="OpenAI",
        role="Processamento de linguagem, visão e transcrição",
        receives=(
            "O texto que você escreve ao assistente, o áudio que você grava e as "
            "fotos de cupom que você envia, junto com o histórico recente da "
            "conversa e as suas regras de memória."
        ),
        country=Country.US,
        url="https://openai.com/policies/privacy-policy",
    ),
    SubProcessor(
        name="Google Cloud",
        role="Hospedagem (Cloud Run), fila de tarefas e armazenamento de arquivos",
        receives=(
            "Tudo que o aplicativo guarda, porque é onde ele roda: o servidor, "
            "os arquivos de importação e exportação e os registros de acesso."
        ),
        country=Country.BR,
        url="https://cloud.google.com/terms/cloud-privacy-notice",
    ),
    SubProcessor(
        name="Supabase",
        role="Banco de dados PostgreSQL gerenciado",
        receives="O banco de dados inteiro: lançamentos, conversas, conta.",
        country=Country.US,
        url="https://supabase.com/privacy",
    ),
    SubProcessor(
        name="Resend",
        role="Envio de e-mail transacional",
        receives=(
            "Seu endereço de e-mail e o conteúdo das mensagens do sistema — "
            "confirmação de cadastro, redefinição de senha, convites."
        ),
        country=Country.US,
        url="https://resend.com/legal/privacy-policy",
    ),
    SubProcessor(
        name="Sentry",
        role="Registro de erros da aplicação",
        receives=(
            "O tipo do erro, o arquivo e a linha. Nunca o conteúdo das suas "
            "requisições, dos seus lançamentos ou das suas conversas — isso é "
            "removido antes do envio."
        ),
        country=Country.US,
        url="https://sentry.io/privacy/",
    ),
    SubProcessor(
        name="Logfire",
        # NOT "duration, model and cost only". `LOGFIRE_CAPTURE_CONTENT`
        # defaults to ON (`settings.py:475`) — an explicit operator decision
        # from E06, whose own comment says: "Logfire then holds chat content and
        # receipt descriptions, which makes Pydantic a data sub-processor of
        # personal financial data. E13's privacy notice must name it." This row
        # is that sentence being honoured. If the flag is ever turned off, this
        # text changes with it — not before.
        role="Rastreamento das chamadas do assistente",
        receives=(
            "Duração, modelo usado e custo de cada chamada de IA — e também o "
            "conteúdo enviado ao modelo e a resposta dele, ou seja, o que você "
            "escreveu ao assistente e o que foi lido do seu cupom. As imagens e "
            "os áudios em si não são enviados."
        ),
        country=Country.US,
        url="https://pydantic.dev/legal/privacy",
    ),
)
