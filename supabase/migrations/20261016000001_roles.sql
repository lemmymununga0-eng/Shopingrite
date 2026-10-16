-- Adds the fraud_analyst and security_analyst roles (the older 'analyst' value keeps working as fraud analyst).
-- NOT run against a live Supabase project in this repository (no credentials): review before applying.
--   viewers : every staff role may read all prediction rows
--   reviewers: only fraud analysts and admins may update review fields
create or replace function public.is_reviewer() returns boolean
language sql stable as $$
  select coalesce(auth.jwt() -> 'app_metadata' ->> 'role', 'customer')
         in ('analyst','fraud_analyst','security_analyst','admin');
$$;

create or replace function public.can_review_alerts() returns boolean
language sql stable as $$
  select coalesce(auth.jwt() -> 'app_metadata' ->> 'role', 'customer') in ('analyst','fraud_analyst','admin');
$$;

drop policy if exists tx_update_reviewer on public.transactions;
create policy tx_update_reviewer on public.transactions for update to authenticated
  using (public.can_review_alerts()) with check (public.can_review_alerts());
