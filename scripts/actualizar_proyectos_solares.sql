-- ============================================================
-- Actualizar proyectos: departamento, municipio, potencia,
-- cantidad de paneles y operador de red
--
-- Uso: pega este script en el editor SQL de Railway
--      (o cualquier cliente PostgreSQL conectado a la DB)
--
-- COALESCE: solo llena campos que estén NULL (no sobreescribe)
-- ============================================================


-- ============================================================
-- PASO 1: Datos técnicos desde proyectos_solares_completo.json
-- ============================================================

-- Almacenes AMC
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Sucre'),
  municipio               = COALESCE(municipio, 'Sincelejo'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 81),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 150)
WHERE nombre_comercial ILIKE '%AMC%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 150 FROM proyectos WHERE nombre_comercial ILIKE '%AMC%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 150);

-- Arboleda de Castilla
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Antioquia'),
  municipio               = COALESCE(municipio, 'Medellín'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 517),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 94)
WHERE nombre_comercial ILIKE '%Arboleda%' AND nombre_comercial ILIKE '%Castilla%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 94 FROM proyectos WHERE nombre_comercial ILIKE '%Arboleda%' AND nombre_comercial ILIKE '%Castilla%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 94);

-- Asociación Asprolesa
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Antioquia'),
  municipio               = COALESCE(municipio, 'Santuario'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 72),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 144)
WHERE nombre_comercial ILIKE '%Asprolesa%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 144 FROM proyectos WHERE nombre_comercial ILIKE '%Asprolesa%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 144);

-- Central de Maderas
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Bolívar'),
  municipio               = COALESCE(municipio, 'Turbaná'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 55),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 140)
WHERE nombre_comercial ILIKE '%Central%' AND nombre_comercial ILIKE '%Madera%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 140 FROM proyectos WHERE nombre_comercial ILIKE '%Central%' AND nombre_comercial ILIKE '%Madera%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 140);

-- Centro Comercial Obelisco
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Antioquia'),
  municipio               = COALESCE(municipio, 'Medellín'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 120),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 283)
WHERE nombre_comercial ILIKE '%Obelisco%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 283 FROM proyectos WHERE nombre_comercial ILIKE '%Obelisco%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 283);

-- Centro Comercial Savanna Plaza
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Antioquia'),
  municipio               = COALESCE(municipio, 'Rionegro'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 460),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 88)
WHERE nombre_comercial ILIKE '%Savanna%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 88 FROM proyectos WHERE nombre_comercial ILIKE '%Savanna%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 88);

-- Clínica Somer
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Antioquia'),
  municipio               = COALESCE(municipio, 'Rionegro'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 272),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 538)
WHERE nombre_comercial ILIKE '%Somer%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 538 FROM proyectos WHERE nombre_comercial ILIKE '%Somer%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 538);

-- Colegio Cristo Rey Bogotá
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Bogotá D.C.'),
  municipio               = COALESCE(municipio, 'Bogotá'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 432),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 80)
WHERE nombre_comercial ILIKE '%Cristo Rey%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 80 FROM proyectos WHERE nombre_comercial ILIKE '%Cristo Rey%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 80);

-- Complejo Industrial Cedillanos
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Antioquia'),
  municipio               = COALESCE(municipio, 'Santa Rosa de Osos'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1208),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2158)
WHERE nombre_comercial ILIKE '%Cedillanos%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2158 FROM proyectos WHERE nombre_comercial ILIKE '%Cedillanos%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2158);

-- Cross Business Center
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Antioquia'),
  municipio               = COALESCE(municipio, 'Medellín'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 534),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 118)
WHERE nombre_comercial ILIKE '%Cross%Business%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 118 FROM proyectos WHERE nombre_comercial ILIKE '%Cross%Business%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 118);

-- Ecoimagen IPS
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Norte de Santander'),
  municipio               = COALESCE(municipio, 'Cúcuta'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 323),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 84)
WHERE nombre_comercial ILIKE '%Ecoimagen%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 84 FROM proyectos WHERE nombre_comercial ILIKE '%Ecoimagen%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 84);

-- Granja Solar San Agustín (sin ciudad/departamento en la fuente)
UPDATE proyectos SET
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1408),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2184)
WHERE nombre_comercial ILIKE '%San Agust%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2184 FROM proyectos WHERE nombre_comercial ILIKE '%San Agust%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2184);

-- Gimnasio San Angelo
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Bogotá D.C.'),
  municipio               = COALESCE(municipio, 'Bogotá'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 767),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 142)
WHERE nombre_comercial ILIKE '%Angelo%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 142 FROM proyectos WHERE nombre_comercial ILIKE '%Angelo%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 142);

-- IML
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Risaralda'),
  municipio               = COALESCE(municipio, 'Pereira'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1321),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2298)
WHERE nombre_comercial = 'IML' OR nombre_comercial ILIKE 'IML%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2298 FROM proyectos WHERE nombre_comercial = 'IML' OR nombre_comercial ILIKE 'IML%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2298);

-- IPS Coopsana
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Antioquia'),
  municipio               = COALESCE(municipio, 'Medellín'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 32),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 80)
WHERE nombre_comercial ILIKE '%Coopsana%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 80 FROM proyectos WHERE nombre_comercial ILIKE '%Coopsana%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 80);

-- Ladrillera Arcillas San Simón
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Norte de Santander'),
  municipio               = COALESCE(municipio, 'El Zulia'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 134),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 252)
WHERE nombre_comercial ILIKE '%Arcillas%' OR nombre_comercial ILIKE '%San Sim%n%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 252 FROM proyectos WHERE nombre_comercial ILIKE '%Arcillas%' OR nombre_comercial ILIKE '%San Sim%n%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 252);

-- Los Coches
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Córdoba'),
  municipio               = COALESCE(municipio, 'Montelíbano'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 449),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 84)
WHERE nombre_comercial ILIKE '%Coches%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 84 FROM proyectos WHERE nombre_comercial ILIKE '%Coches%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 84);

-- MDM Científica
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Antioquia'),
  municipio               = COALESCE(municipio, 'Medellín'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 528),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 132)
WHERE nombre_comercial ILIKE '%MDM%' OR nombre_comercial ILIKE '%Cient%fica%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 132 FROM proyectos WHERE nombre_comercial ILIKE '%MDM%' OR nombre_comercial ILIKE '%Cient%fica%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 132);

-- MGS 0004 Valle de Gandalf
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Cesar'),
  municipio               = COALESCE(municipio, 'San Diego'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1316),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2308)
WHERE nombre_comercial ILIKE '%Gandalf%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2308 FROM proyectos WHERE nombre_comercial ILIKE '%Gandalf%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2308);

-- MGS 0005 Cañahuate
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Cesar'),
  municipio               = COALESCE(municipio, 'San Diego'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1316),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2308)
WHERE nombre_comercial ILIKE '%Ca%ahuate%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2308 FROM proyectos WHERE nombre_comercial ILIKE '%Ca%ahuate%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2308);

-- MGS 0006 Perijá
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Cesar'),
  municipio               = COALESCE(municipio, 'San Diego'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1312),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2280)
WHERE nombre_comercial ILIKE '%Perij%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2280 FROM proyectos WHERE nombre_comercial ILIKE '%Perij%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2280);

-- MGS 0007 La Paz Vallenata
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Cesar'),
  municipio               = COALESCE(municipio, 'La Paz'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1330),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2300)
WHERE nombre_comercial ILIKE '%Vallenata%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2300 FROM proyectos WHERE nombre_comercial ILIKE '%Vallenata%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2300);

-- MGS 0008 La Paz Verso
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Cesar'),
  municipio               = COALESCE(municipio, 'La Paz'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1339),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2308)
WHERE nombre_comercial ILIKE '%Verso%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2308 FROM proyectos WHERE nombre_comercial ILIKE '%Verso%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2308);

-- MGS 0009 El Molino
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'La Guajira'),
  municipio               = COALESCE(municipio, 'El Molino'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1315),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2280)
WHERE nombre_comercial ILIKE '%Molino%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2280 FROM proyectos WHERE nombre_comercial ILIKE '%Molino%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2280);

-- MGS 0010 Villanueva
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'La Guajira'),
  municipio               = COALESCE(municipio, 'Villanueva'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1339),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2308)
WHERE nombre_comercial ILIKE '%Villanueva%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2308 FROM proyectos WHERE nombre_comercial ILIKE '%Villanueva%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2308);

-- MGS 0011 El Roble
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Sucre'),
  municipio               = COALESCE(municipio, 'El Roble'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1339),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2308)
WHERE nombre_comercial ILIKE '%Roble%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2308 FROM proyectos WHERE nombre_comercial ILIKE '%Roble%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2308);

-- MGS 0013 La Mesa
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Santander'),
  municipio               = COALESCE(municipio, 'Los Santos'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1340),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2196)
WHERE nombre_comercial ILIKE '%La Mesa%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2196 FROM proyectos WHERE nombre_comercial ILIKE '%La Mesa%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2196);

-- MGS 0014 El Olimpo
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Santander'),
  municipio               = COALESCE(municipio, 'Los Santos'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1322),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2196)
WHERE nombre_comercial ILIKE '%Olimpo%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2196 FROM proyectos WHERE nombre_comercial ILIKE '%Olimpo%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2196);

-- MGS 0016 La Puya
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Cesar'),
  municipio               = COALESCE(municipio, 'Valledupar'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1300),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2032)
WHERE nombre_comercial ILIKE '%Puya%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2032 FROM proyectos WHERE nombre_comercial ILIKE '%Puya%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2032);

-- MGS 0017 La Paz Esmeralda
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Cesar'),
  municipio               = COALESCE(municipio, 'La Paz'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1321),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2196)
WHERE nombre_comercial ILIKE '%Esmeralda%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2196 FROM proyectos WHERE nombre_comercial ILIKE '%Esmeralda%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2196);

-- MGS 0018 La Paz Leyenda
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Cesar'),
  municipio               = COALESCE(municipio, 'La Paz'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1318),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2196)
WHERE nombre_comercial ILIKE '%Leyenda%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2196 FROM proyectos WHERE nombre_comercial ILIKE '%Leyenda%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2196);

-- MGS 0019 El Merengue
UPDATE proyectos SET
  departamento            = COALESCE(departamento, 'Cesar'),
  municipio               = COALESCE(municipio, 'Valledupar'),
  potencia_instalada_kwp  = COALESCE(potencia_instalada_kwp, 1322),
  cantidad_total_paneles  = COALESCE(cantidad_total_paneles, 2280)
WHERE nombre_comercial ILIKE '%Merengue%';

INSERT INTO proyecto_info_tecnica (proyecto_id, cantidad_total_paneles)
  SELECT id, 2280 FROM proyectos WHERE nombre_comercial ILIKE '%Merengue%'
ON CONFLICT (proyecto_id) DO UPDATE
  SET cantidad_total_paneles = COALESCE(proyecto_info_tecnica.cantidad_total_paneles, 2280);


-- ============================================================
-- PASO 2: Operadores de Red
-- ============================================================

UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%Perij%'      AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%El Son%'     AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Air-e'  WHERE nombre_comercial ILIKE '%Molino%'     AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%Puya%'       AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Air-e'  WHERE nombre_comercial ILIKE '%Villanueva%' AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'ESSA'   WHERE nombre_comercial ILIKE '%Reserva%'    AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%Ca%ahuate%'  AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%Leyenda%'    AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%Verso%'      AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%San Pedro%'  AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%Vallenata%'  AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%Gandalf%'    AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Air-e'  WHERE nombre_comercial ILIKE '%Uruaco%'     AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%Baraya%'     AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%Esmeralda%'  AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%Merengue%'   AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'ESSA'   WHERE nombre_comercial ILIKE '%Olimpo%'     AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%Ibirico%'    AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'ESSA'   WHERE nombre_comercial ILIKE '%La Mesa%'    AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%San Diego Sur%' AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%Cacica%'     AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%La Molina%'  AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%Cumbia%'     AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%Valencia 1%' AND (operador_red IS NULL OR operador_red = '');
UPDATE proyectos SET operador_red = 'Afinia' WHERE nombre_comercial ILIKE '%Valencia 2%' AND (operador_red IS NULL OR operador_red = '');


-- ============================================================
-- Verificacion final: proyectos con campos aun vacios
-- ============================================================
SELECT nombre_comercial,
       CASE WHEN departamento          IS NULL THEN 'depto ' ELSE '' END ||
       CASE WHEN municipio             IS NULL THEN 'muni ' ELSE '' END ||
       CASE WHEN potencia_instalada_kwp IS NULL THEN 'kwp ' ELSE '' END ||
       CASE WHEN cantidad_total_paneles IS NULL THEN 'paneles ' ELSE '' END ||
       CASE WHEN operador_red          IS NULL THEN 'OR' ELSE '' END AS campos_vacios
FROM proyectos
WHERE departamento IS NULL
   OR municipio IS NULL
   OR potencia_instalada_kwp IS NULL
   OR cantidad_total_paneles IS NULL
   OR operador_red IS NULL
ORDER BY nombre_comercial;
