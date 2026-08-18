# pg_dump must match the server: Supabase runs PostgreSQL 17.6, and pg_dump
# refuses to talk to a newer server (docs/runbook.md, "Applying a migration to
# Supabase", failure #1). Ubuntu's client 16 is what bit us there.
FROM postgres:17

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -sSL https://sdk.cloud.google.com | bash -s -- --disable-prompts --install-dir=/opt
ENV PATH="/opt/google-cloud-sdk/bin:$PATH"

COPY deploy/backup/backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh
ENTRYPOINT ["/usr/local/bin/backup.sh"]
