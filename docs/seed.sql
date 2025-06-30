-- Subscription Plans
INSERT INTO subscription_plans (stripe_price_id, name, description, type, amount, currency)
VALUES 
('price_1RewUxDGa367uEb7bVEOW3fz', 'Monthly Plan', 'Access to all features for a month', 'monthly', 19.00, 'SGD'),
('price_1RewTJDGa367uEb7vAARgGnF', 'Yearly Plan', 'Discounted yearly subscription', 'yearly', 99.00, 'SGD');
