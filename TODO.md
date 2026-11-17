Des idées qui vont avec ton plugin QGIS

Carte du Wi-Fi de l’appartement : à chaque instant, tu as la position du robot (/api/v2/robot/state) et la force du signal Wi-Fi (capability WifiStatus). Tu enregistres les deux pendant un nettoyage, puis tu fais une interpolation dans QGIS (IDW ou TIN) et tu obtiens la carte de couverture Wi-Fi de chez toi. L’outil Valeronoi fait déjà ça pour Valetudo, mais le refaire dans QGIS est beaucoup plus drôle.
Faire dessiner le robot : tu traces une polyligne dans QGIS et le robot la suit point par point avec GoToLocation. Avec la serpillière humide, il laisse un dessin éphémère sur le carrelage.
Statistiques de nettoyage : tu gardes les trajectoires de chaque passage dans un GeoPackage et tu en tires une carte de chaleur des zones les plus nettoyées et de celles qu’il oublie (sous le canapé…).
Plan de l’appartement : le LiDAR donne une carte précise au centimètre. Tu peux mesurer les surfaces des pièces, vectoriser les murs et superposer un vrai plan.

Avec la caméra (le flux H.264 sur le port 8555)

Ronde de surveillance : tu l’envoies sur quelques points de passage, il prend une image à chaque arrêt, et tu reçois une notification. Pratique pendant les vacances.
Détection d’objets : tu branches le flux sur Frigate ou un petit modèle YOLO pour repérer le chat, des chaussettes ou autre chose.
Timelapse d’un nettoyage, vu du robot.

Domotique (MQTT et Home Assistant)

Lancer le nettoyage quand tout le monde est sorti, et le mettre en pause quand quelqu’un rentre ou décroche le téléphone.
Ajouter la carte en direct sur le tableau de bord (la carte lovelace-xiaomi-vacuum-map-card prend en charge Valetudo).
Recevoir une alerte quand le sac de la station est plein ou quand une brosse arrive en fin de vie.

password pour ssg raspeberry