-- SHA-256 of every file in a version's bundle, recorded by the pipeline when it writes the version. The serving
-- side loads a bundle (joblib runs code) only when the downloaded files match these hashes.
alter table public.versions add column artifact_files jsonb;
