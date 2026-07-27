-- What kind of protection a listed patent actually is.
--
-- The Orange Book flags each patent as drug substance, drug product, or neither, and
-- carries a use code when it covers a method of use. Those are different obstacles to a
-- generic. The substance patent covers the molecule and has to expire before anyone can
-- sell it at all. A method-of-use patent covers one indication, and a generic can launch
-- with that indication carved out of its label.
--
-- Storing only the dates made Mounjaro read "2027 to 2041", which mixes a regulatory
-- exclusivity that ends in 2027 with a use patent running to 2041, and states neither
-- what it is. Its substance patent expires in 2039.
--
-- 'substance', 'product', 'use' or null for a patent the book flags as none of them.

ALTER TABLE exclusivities ADD COLUMN patent_kind TEXT;
