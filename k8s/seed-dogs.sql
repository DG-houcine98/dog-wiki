-- Seed the dogs table with rows that match the photos in S3.
-- Run after the app has come up at least once (so the dogs table exists).
--   kubectl cp k8s/seed-dogs.sql prod/<postgres-pod>:/tmp/seed.sql
--   kubectl exec -n prod <postgres-pod> -- psql -U postgres -d dogsdb -f /tmp/seed.sql

INSERT INTO dogs (id, breed, description, photo_key) VALUES
  ('1f934c4d-86ae-4ef2-bdec-8a72c8545cd3', 'Golden Retriever',           'Friendly, intelligent, devoted family dog with a gentle temperament.', 'dogs/GoldenRetreiver.webp'),
  ('adb17660-471a-4725-bbb0-00e6442710dd', 'Greater Swiss Mountain Dog', 'Strong, athletic Swiss working breed with a striking tricolor coat.',  'dogs/GreaterSwissMountainDog.webp'),
  ('e90e485e-035f-4d0e-82a9-946478fc0b8d', 'Shiba Inu',                  'Small, agile Japanese breed; bold, alert, and famously stubborn.',     'dogs/ShibaInu.webp')
ON CONFLICT (id) DO UPDATE SET
  breed       = EXCLUDED.breed,
  description = EXCLUDED.description,
  photo_key   = EXCLUDED.photo_key;
