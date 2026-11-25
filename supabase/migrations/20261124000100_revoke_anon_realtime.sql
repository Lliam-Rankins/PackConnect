-- Undo anonymous table access from the withdrawn 20261120000100_realtime_chat migration.
-- Safe to run whether or not that migration was ever applied.
BEGIN;

DROP POLICY IF EXISTS "allow_anon_read_chat_messages" ON public.chat_messages;
DROP POLICY IF EXISTS "allow_anon_read_notifications" ON public.notifications;

REVOKE SELECT ON TABLE public.chat_messages, public.notifications FROM anon;

DO $$
DECLARE
    target record;
BEGIN
    FOR target IN
        SELECT schemaname, tablename FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND schemaname = 'public'
            AND tablename IN ('chat_messages', 'notifications')
    LOOP
        EXECUTE format('ALTER PUBLICATION supabase_realtime DROP TABLE %I.%I',
                       target.schemaname, target.tablename);
    END LOOP;
END $$;

ALTER TABLE public.chat_messages REPLICA IDENTITY DEFAULT;
ALTER TABLE public.notifications REPLICA IDENTITY DEFAULT;

COMMIT;
