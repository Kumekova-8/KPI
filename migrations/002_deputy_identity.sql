ALTER TABLE deputies ADD COLUMN person TEXT;
UPDATE deputies SET person=id WHERE person IS NULL;
CREATE INDEX deputy_person ON deputies(person);

