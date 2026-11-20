BEGIN;

-- 1. Conditionally add tables to supabase_realtime publication
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime') THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE public.chat_messages;
        ALTER PUBLICATION supabase_realtime ADD TABLE public.notifications;
    END IF;
END $$;

-- 2. Configure replica identity
ALTER TABLE public.chat_messages REPLICA IDENTITY FULL;
ALTER TABLE public.notifications REPLICA IDENTITY FULL;

-- 3. Grant SELECT privileges to anon role
GRANT SELECT ON TABLE public.chat_messages TO anon;
GRANT SELECT ON TABLE public.notifications TO anon;

-- 4. Create RLS read policies for anon role
DROP POLICY IF EXISTS "allow_anon_read_chat_messages" ON public.chat_messages;
CREATE POLICY "allow_anon_read_chat_messages"
    ON public.chat_messages
    FOR SELECT
    TO anon
    USING (true);

DROP POLICY IF EXISTS "allow_anon_read_notifications" ON public.notifications;
CREATE POLICY "allow_anon_read_notifications"
    ON public.notifications
    FOR SELECT
    TO anon
    USING (true);

COMMIT;
