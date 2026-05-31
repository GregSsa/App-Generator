# AI Android App Generator

Prototype LangGraph multi-agents qui transforme une idee d'application Android en projet Kotlin / Jetpack Compose exportable.

## Objectif

Le workflow simule une petite equipe logicielle :

- Product Manager : extrait les besoins fonctionnels.
- Architect : choisit une architecture Android coherente.
- UI Agent : decrit les ecrans Compose.
- Build Config Developer : prepare Gradle, plugins, versions et dependances.
- Data Developer : gere modeles, repository et limites de persistence.
- UI Developer : prepare les composables Jetpack Compose.
- Integration Developer : assemble les plans specialises en projet coherent.
- QA / Validator : verifie la coherence du projet genere.
- Fix Agent : identifie le plus petit developpeur specialise a relancer.
- Supervisor LangGraph : orchestre les noeuds, l'etat partage et la boucle validation -> correction.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

OpenAI est le mode agent par defaut. Pour activer les appels reels, configurez une cle API :

```powershell
pip install -e ".[openai]"
copy .env.example .env
```

## Utilisation

Generer un projet Android :

```powershell
ai-android-generator.exe "Creer une application Android de suivi de mangas avec notifications" --output generated/MangaTracker
```

Diagnostiquer un run long :

```powershell
ai-android-generator.exe "Creer une application Android qui affiche Hello World" --verbose --openai-timeout 25
```

`--verbose` affiche les noeuds LangGraph termines et les appels OpenAI en cours.

Ou avec Python :

```powershell
python -m ai_android_app_generator "Tracker de mangas avec notifications de nouveaux chapitres"
```

Mode local deterministe, sans appels OpenAI :

```powershell
python -m ai_android_app_generator "Tracker de mangas avec notifications" --local
```

Dry run sans LangGraph, mais avec les memes agents :

```powershell
python -m ai_android_app_generator "Tracker de mangas avec notifications" --sequential
```

Avec le mode OpenAI actif, chaque agent du workflow tente son propre appel OpenAI :
Product Manager, Architect, UI, Build Config Developer, Data Developer, UI Developer,
Integration Developer, QA Validator et Fix Agent. Si la cle API ou l'extra Python manque,
l'agent journalise le probleme et utilise son fallback local.

Le graphe evite de demander a un seul developpeur de tout produire en une fois :

```text
Product Manager
  -> Architect
  -> UI Agent
  -> Build Config Developer
  -> Data Developer
  -> UI Developer
  -> Integration Developer
  -> QA Validator
  -> Fix Agent
      -> build_config | data | ui | integration
      -> Integration Developer
      -> QA Validator
```

Les prompts des developpeurs imposent une barre qualite explicite : moins de code,
code compilable, pas de couches inutiles, imports coherents, responsabilites separees,
et respect strict du profil d'application.

Les agents OpenAI disposent aussi d'outils de lecture selective sur le projet genere :

- `list_project_files` : lister les fichiers disponibles.
- `read_project_files` : demander le contenu de fichiers precis.
- `search_project_files` : rechercher une chaine dans les fichiers.

Le runtime execute ces demandes et renvoie seulement les extraits utiles a l'agent.
Cela evite d'envoyer tout le projet dans chaque prompt, tout en permettant au QA,
au Fix Agent et aux developpeurs specialises de relire le code deja produit.

Le Product Manager choisit aussi un profil d'application :

- `static_text` : app Compose minimale pour un ecran statique type Hello World.
- `data_driven` : app MVVM avec modeles, repository, ViewModel et liste Compose.

Le fichier Gradle genere aligne Java et Kotlin sur une JVM toolchain 17 pour eviter
les erreurs du type `compileDebugJavaWithJavac (1.8)` vs `compileDebugKotlin (21)`.

Le resultat contient un projet Gradle Android quasi pret a ouvrir dans Android Studio.

## Structure

```text
src/ai_android_app_generator/
  agents.py           Agents metier deterministes et extensibles
  android_project.py  Generation des fichiers Android
  graph.py            Graphe LangGraph, developpeurs specialises et routage conditionnel
  state.py            Etat partage entre agents
  cli.py              Interface ligne de commande
tests/                Tests unitaires du workflow sans appel reseau
```

## Notes

Le coeur reste testable localement, mais le chemin principal est OpenAI-first. Les fallbacks deterministes evitent qu'un prototype soit bloque par une cle API manquante pendant le developpement.
