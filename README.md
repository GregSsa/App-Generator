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
- Build Agent : exporte le projet, lance Gradle si disponible et recupere les erreurs.
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

Les outils de lecture de fichiers utilisent le Filesystem MCP Server. Le client Python MCP
est installe avec l'extra `openai`, et le serveur est lance par defaut avec :

```powershell
npx -y @modelcontextprotocol/server-filesystem <snapshot-temporaire-du-projet>
```

Node.js/npm doivent donc etre disponibles pour les runs reels. Vous pouvez remplacer la
commande serveur si besoin :

```powershell
$env:AI_GENERATOR_MCP_FILESYSTEM_COMMAND='npx'
$env:AI_GENERATOR_MCP_FILESYSTEM_ARGS='["-y","@modelcontextprotocol/server-filesystem","{root}"]'
```

## Utilisation

Generer un projet Android :

```powershell
ai-android-generator.exe "Creer une application Android de suivi de mangas avec notifications" --output generated/MangaTracker
```

Diagnostiquer un run long :

```powershell
ai-android-generator.exe "Creer une application Android qui affiche Hello World" --verbose
```

`--verbose` affiche les noeuds LangGraph termines et les appels OpenAI en cours.

Pour desactiver LangSmith sur un run local :

```powershell
$env:LANGSMITH_TRACING='false'
```

Ou avec Python :

```powershell
python -m ai_android_app_generator "Tracker de mangas avec notifications de nouveaux chapitres"
```

Dry run sans LangGraph, mais avec les memes agents :

```powershell
python -m ai_android_app_generator "Tracker de mangas avec notifications" --sequential
```

Avec le mode OpenAI actif, chaque agent du workflow tente son propre appel OpenAI :
Product Manager, Architect, UI, Build Config Developer, Data Developer, UI Developer,
Integration Developer, QA Validator et Fix Agent.

Si un appel OpenAI echoue, la generation est annulee avec `status=failed` et aucun
projet de secours n'est exporte. Une reponse OpenAI incomplete sur les cles obligatoires
annule aussi la generation au lieu de basculer vers une valeur inventee localement.

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
  -> Build Agent
  -> Fix Agent
      -> build_config | data | ui | integration
      -> Integration Developer
      -> QA Validator
      -> Build Agent
```

Les prompts des developpeurs imposent une barre qualite explicite : moins de code,
code compilable, pas de couches inutiles, imports coherents, responsabilites separees,
et respect strict du profil d'application.

Les LLM disposent d'une toolbox Android explicite pour choisir les bonnes briques :

- Material 3 + Compose adaptive : UI Compose et layouts adaptatifs si necessaire.
- Navigation Compose / Navigation 3 : navigation multi-ecrans et back stack.
- Room : persistance locale structuree et offline-first.
- DataStore : preferences et petits reglages persistants.
- WorkManager : taches de fond, sync et notifications fiables.
- Retrofit/Ktor : integration HTTP/API distante.
- Coil : chargement d'images, covers, avatars, posters.

Ces outils ne sont pas ajoutes automatiquement a toutes les apps. Les agents doivent les
selectionner seulement quand le prompt ou les requirements le justifient.

Les agents OpenAI disposent aussi d'outils de lecture selective sur le projet genere.
Ces outils ne sont plus un pseudo-MCP local : le runtime cree un snapshot temporaire
des fichiers en memoire, lance un vrai Filesystem MCP Server sur ce repertoire, puis
execute les demandes de l'agent via MCP.

- `list_project_files` : lister les fichiers disponibles.
- `read_project_files` : demander le contenu de fichiers precis.
- `search_project_files` : rechercher une chaine dans les fichiers.

Le runtime execute ces demandes et renvoie seulement les extraits utiles a l'agent.
Cela evite d'envoyer tout le projet dans chaque prompt, tout en permettant au QA,
au Fix Agent et aux developpeurs specialises de relire le code deja produit.

L'Integration Developer peut ensuite retourner des patches cibles au lieu de demander
une regeneration complete :

```json
{
  "implementation_plan": {
    "file_patches": [
      {
        "op": "replace_text",
        "path": "app/src/main/java/com/generated/app/MainActivity.kt",
        "old": "Hello",
        "new": "Hello World"
      }
    ]
  }
}
```

Operations supportees : `replace_text`, `upsert_file`, `delete_file`. Les chemins sont
valides pour le projet genere uniquement.

Le Product Manager choisit aussi un profil d'application :

- `static_text` : app Compose minimale pour un ecran statique type Hello World.
- `data_driven` : app MVVM avec modeles, repository, ViewModel et liste Compose.

Le fichier Gradle genere aligne Java et Kotlin sur une JVM toolchain 17 pour eviter
les erreurs du type `compileDebugJavaWithJavac (1.8)` vs `compileDebugKotlin (21)`.

La generation Kotlin utilise une couche de construction type KotlinPoet (`KotlinFileSpec`) :
les fichiers Kotlin sont construits avec package, imports tries et declarations separees,
plutot qu'avec un seul gros bloc texte. Cette couche sert uniquement a assembler un projet
a partir des plans OpenAI valides ; elle ne sert pas de fallback local quand la generation
LLM echoue.

Le resultat contient un projet Gradle Android quasi pret a ouvrir dans Android Studio.

## Structure

```text
src/ai_android_app_generator/
  agents.py           Agents metier OpenAI et extensibles
  android_project.py  Generation des fichiers Android
  kotlin_templates.py Construction Kotlin type FileSpec/KotlinPoet
  graph.py            Graphe LangGraph, developpeurs specialises et routage conditionnel
  mcp_filesystem.py   Bridge vers le Filesystem MCP Server
  state.py            Etat partage entre agents
  cli.py              Interface ligne de commande
tests/                Tests unitaires du workflow sans appel reseau
```

## Notes

Les tests utilisent des reponses OpenAI simulees, mais l'application en execution attend de
vrais agents OpenAI et echoue explicitement si la generation LLM ne fonctionne pas.
