UPDATE users SET custom_permissions = custom_permissions || ',outlook'
 WHERE COALESCE(custom_permissions, '') <> ''
   AND (role IN ('System Administrator', 'Inventory Personnel', 'Management/Owner')
        OR (',' || custom_permissions || ',') LIKE '%,inventory,%')
   AND (',' || custom_permissions || ',') NOT LIKE '%,outlook,%';
