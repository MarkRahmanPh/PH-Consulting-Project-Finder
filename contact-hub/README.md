# PH Consulting Contact Hub

This is a separate application inside the existing PH Consulting Project Finder repository.

## Security
Do not commit contact spreadsheets, seed JSON/CSV, credentials, or private conference notes to this repository. GitHub Pages files are publicly accessible even if a repository is private. Store contact records in Supabase with Row Level Security and an explicit staff allowlist.

## Deployment
The current index.html is a safe placeholder. Before enabling the full app, configure Supabase authentication, authorized staff list, RLS policies, and import records privately. Then deploy the frontend using only a Supabase publishable/anon key (never a service-role key).
