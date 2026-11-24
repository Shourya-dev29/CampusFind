-- CampusFind uses Flask sessions and a server-side PostgreSQL connection.
-- Apply to existing CampusFind tables; never grant client-side access to these tables.
BEGIN;
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.users, public.items, public.claims, public.notifications FROM anon, authenticated, PUBLIC;
REVOKE ALL ON SEQUENCE public.users_id_seq, public.items_id_seq, public.claims_id_seq, public.notifications_id_seq FROM anon, authenticated, PUBLIC;
CREATE INDEX IF NOT EXISTS idx_claims_claimant_id ON public.claims(claimant_id);
CREATE INDEX IF NOT EXISTS idx_claims_item_id ON public.claims(item_id);
CREATE INDEX IF NOT EXISTS idx_items_user_id ON public.items(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_related_item_id ON public.notifications(related_item_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON public.notifications(user_id);
COMMIT;
