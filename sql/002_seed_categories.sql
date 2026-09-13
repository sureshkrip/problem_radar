-- Seed the two taxonomy axes. Categories live in a table (not an enum column) so they can be
-- renamed or merged later without touching problem rows. Re-runnable: ON CONFLICT DO NOTHING.

INSERT INTO category (axis, slug, name) VALUES
  ('industry', 'real-estate',            'Real Estate'),
  ('industry', 'healthcare',             'Healthcare'),
  ('industry', 'education',              'Education'),
  ('industry', 'legal',                  'Legal'),
  ('industry', 'finance-accounting',     'Finance & Accounting'),
  ('industry', 'insurance',              'Insurance'),
  ('industry', 'logistics-supply-chain', 'Logistics & Supply Chain'),
  ('industry', 'construction-trades',    'Construction & Trades'),
  ('industry', 'retail-ecommerce',       'Retail & E-commerce'),
  ('industry', 'hospitality-food',       'Hospitality & Food'),
  ('industry', 'manufacturing',          'Manufacturing'),
  ('industry', 'agriculture',            'Agriculture'),
  ('industry', 'nonprofit-government',   'Nonprofit & Government'),
  ('industry', 'media-creative',         'Media & Creative'),
  ('industry', 'hr-recruiting',          'HR & Recruiting'),
  ('industry', 'it-devops',              'IT & DevOps'),
  ('industry', 'sales-marketing',        'Sales & Marketing'),
  ('industry', 'personal-consumer',      'Personal & Consumer'),
  ('industry', 'other',                  'Other')
ON CONFLICT (axis, slug) DO NOTHING;

INSERT INTO category (axis, slug, name) VALUES
  ('function', 'data-entry-extraction',  'Data Entry & Extraction'),
  ('function', 'scheduling-dispatch',    'Scheduling & Dispatch'),
  ('function', 'document-generation',    'Document Generation'),
  ('function', 'compliance-reporting',   'Compliance & Reporting'),
  ('function', 'communication-followup', 'Communication & Follow-up'),
  ('function', 'search-discovery',       'Search & Discovery'),
  ('function', 'pricing-quoting',        'Pricing & Quoting'),
  ('function', 'invoicing-payments',     'Invoicing & Payments'),
  ('function', 'monitoring-alerting',    'Monitoring & Alerting'),
  ('function', 'integration-sync',       'Integration & Sync'),
  ('function', 'analytics-reporting',    'Analytics & Reporting'),
  ('function', 'intake-onboarding',      'Intake & Onboarding'),
  ('function', 'inventory-tracking',     'Inventory Tracking'),
  ('function', 'other',                  'Other')
ON CONFLICT (axis, slug) DO NOTHING;
