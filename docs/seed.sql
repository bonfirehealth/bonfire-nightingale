-- Subscription Plans
INSERT INTO subscription_plans (stripe_price_id, name, description, type, amount, currency)
VALUES 
('price_1Rp4wXJrqghNBp9AHHygAA6m', 'Nightingale (Monthly Plan)', 'Nightingale is your on-demand focus-training coach for your child’s executive functioning, studying strategies, and ADHD support. Co-designed with child psychologists, you’ll get unlimited chat and phone consults, unlimited consultation summaries, and progress tracking. Pay monthly, cancel anytime.', 'monthly', 99.00, 'SGD'),
('price_1Rp4yFJrqghNBp9Ak0LG29VG', 'Get 12 months of Nightingale - your on-demand focus-training coach for your child’s executive functioning, studying strategies, and ADHD support. Co-designed with child psychologists, you’ll get unlimited chat and phone consults, unlimited consultation summaries, progress tracking, and over 40% in savings. One-time payment. Cancel auto-renew anytime.', 'yearly', 699.00, 'SGD');
