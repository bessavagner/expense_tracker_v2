# pg_dump must match the server: Supabase runs PostgreSQL 17.6, and pg_dump
# refuses to talk to a newer server (docs/runbook.md, "Applying a migration to
# Supabase", failure #1). Ubuntu's client 16 is what bit us there.
FROM postgres:17

# curl and python3 only. The first version of this image installed the whole
# Google Cloud SDK to get `gcloud storage cp`, and it failed at run time with
# "You do not currently have an active account selected" — an SDK installed that
# way does not pick up Cloud Run's metadata credentials. Uploading straight to
# the GCS JSON API with a metadata-server token needs neither the SDK nor a key,
# and cuts several minutes off every image build.
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/backup/backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh
ENTRYPOINT ["/usr/local/bin/backup.sh"]
