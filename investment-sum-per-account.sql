SELECT (
		SELECT (
			CASE 
				WHEN NOT c.namespace = 'CURRENCY' THEN
				SUM(
					(s.quantity_num / CAST(s.quantity_denom AS FLOAT)) -- amount of shares
					*
					(SELECT
						p.value_num / CAST (p.value_denom AS FLOAT) -- last quoted price of the share
					FROM 
						prices p 
					WHERE 
						a_c.commodity_guid = p.commodity_guid ORDER BY datetime(p.date) DESC LIMIT 1)
				)	
				ELSE SUM(s.value_num / CAST(s.value_denom AS FLOAT)) -- it's already currency
			END
		)
		FROM 
			splits s JOIN
			accounts a_c ON s.account_guid = a_c.guid JOIN
			commodities c ON a_c.commodity_guid = c.guid
		WHERE 
			s.account_guid IN (SELECT guid FROM accounts WHERE a_c.parent_guid = a.guid) -- filter all children
	) AS value,
	a.name
FROM 
	accounts a
WHERE
	a.hidden = false and a.parent_guid = (SELECT guid FROM accounts WHERE name = 'Investimentos') and value is not null;
