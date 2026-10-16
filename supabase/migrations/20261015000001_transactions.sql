-- Shoprite FraudGuard: transactions + alert review, with Row Level Security.
-- Apply in the Supabase dashboard: SQL Editor -> paste -> Run (or `supabase db push`).
--
-- Roles: stored in auth.users.raw_app_meta_data -> {"role": "analyst" | "admin"}. Users cannot edit
-- app_metadata themselves; set it from the dashboard (see README). No role = customer.

create table if not exists public.transactions (
  id                     uuid primary key default gen_random_uuid(),
  user_id                uuid not null references auth.users(id) on delete cascade,
  transaction_reference  text not null check (char_length(transaction_reference) between 3 and 40),
  amount                 numeric(14,2) not null check (amount > 0 and amount <= 1000000),
  payment_method         text not null check (payment_method in ('Card','Bank Transfer','Mobile Money')),
  hour                   smallint not null check (hour between 0 and 23),
  failed_attempts        smallint not null check (failed_attempts between 0 and 10),
  new_device             boolean not null,
  international          boolean not null,
  customer_avg_spend     numeric(14,2) not null check (customer_avg_spend >= 0),
  branch                 text not null,
  probability            double precision not null check (probability between 0 and 1),
  risk                   text not null check (risk in ('Low','Medium','High')),
  prediction             text not null,
  is_flagged             boolean not null,
  model_version          text not null,
  contributing_factors   jsonb not null default '[]'::jsonb,
  review_status          text check (review_status in ('new','confirmed_fraud','false_positive')),
  review_notes           text check (char_length(review_notes) <= 1000),
  reviewed_by            uuid references auth.users(id),
  reviewed_at            timestamptz,
  created_at             timestamptz not null default now(),
  -- only flagged transactions are alerts and carry a review status
  constraint review_only_when_flagged check (is_flagged or review_status is null)
);

create index if not exists idx_transactions_user_created on public.transactions (user_id, created_at desc);
create index if not exists idx_transactions_flagged on public.transactions (is_flagged, review_status);

-- Helper: is the caller an analyst or admin? (reads the signed token, not user-editable data)
create or replace function public.is_reviewer() returns boolean
language sql stable as $$
  select coalesce(auth.jwt() -> 'app_metadata' ->> 'role', 'customer') in ('analyst','admin');
$$;

alter table public.transactions enable row level security;
alter table public.transactions force row level security;

drop policy if exists tx_select on public.transactions;
create policy tx_select on public.transactions for select to authenticated
  using (user_id = auth.uid() or public.is_reviewer());

drop policy if exists tx_insert on public.transactions;
create policy tx_insert on public.transactions for insert to authenticated
  with check (user_id = auth.uid());

-- Only reviewers may update (used for alert review). No delete policy: nobody can delete via the API.
drop policy if exists tx_update_reviewer on public.transactions;
create policy tx_update_reviewer on public.transactions for update to authenticated
  using (public.is_reviewer()) with check (public.is_reviewer());

-- Even reviewers may only change review columns.
create or replace function public.guard_transaction_update() returns trigger
language plpgsql as $$
begin
  if (new.id, new.user_id, new.transaction_reference, new.amount, new.probability, new.risk,
      new.prediction, new.is_flagged, new.model_version, new.created_at)
     is distinct from
     (old.id, old.user_id, old.transaction_reference, old.amount, old.probability, old.risk,
      old.prediction, old.is_flagged, old.model_version, old.created_at) then
    raise exception 'Only review fields can be updated';
  end if;
  return new;
end $$;

drop trigger if exists trg_guard_transaction_update on public.transactions;
create trigger trg_guard_transaction_update before update on public.transactions
  for each row execute function public.guard_transaction_update();

revoke all on public.transactions from anon;
grant select, insert, update on public.transactions to authenticated;
