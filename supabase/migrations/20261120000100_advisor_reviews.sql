BEGIN;

CREATE TABLE IF NOT EXISTS public.advice_reviews (
    request_id bigint PRIMARY KEY REFERENCES public.advice_requests(id) ON DELETE CASCADE,
    rating smallint NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment text NOT NULL DEFAULT '' CHECK (char_length(comment) <= 1000),
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.advice_reviews ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.advice_reviews FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.advice_reviews TO service_role;

NOTIFY pgrst, 'reload schema';
COMMIT;
