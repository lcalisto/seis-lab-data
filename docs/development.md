# Development

This document is project deliverable _D03 - Developer-oriented documentation on how to stand up the project_. It
contains information on how to set up a local development environment suitable for working on the SeisLabData project.

This project is composed of a set of multiple services which are deployed with `docker compose`. The
`docker/compose.dev.yaml` file is a compose file suitable for development

!!! tip
    When the development docker stack is up and running, run docker compose commands with this incantation:

    ```shell
    docker compose -f docker/compose.dev.yaml <docker-command> <service-name>
    ```

    This makes it easier to scope the commands to this project

The more relevant services are:

- `webapp` - the main web application, which is implemented with [starlette], [sqlmodel], [jinja] and [datastar]
- `interactive-worker` - the [dramatiq] worker that runs the quick, user-facing tasks, such as
  the state-changing DB modifications (create, update, delete, validate, publish). It consumes the
  `default` queue
- `long-tasks-worker` - the [dramatiq] worker that runs the tasks which may take long: previews,
  thumbnails and exports. It consumes the `previews`, `thumbnails` and `exports` queues, so these
  tasks never delay the interactive ones
- `discovery-worker` - the [dramatiq] worker that runs archive discoveries, from the `discovery`
  queue. It runs one process, discovering one mission at a time; set `DISCOVERY_WORKER_PROCESSES`
  in the environment of `docker compose` to discover several missions in parallel
- `message-broker` - a [redis] instance that passes messages between the webapp and the workers
- `web-gateway` - a [traefik] instance that acts as a reverse proxy for the system
- `auth-webapp` - an [authentik] instance that takes care of user authentication

[authentik]: https://goauthentik.io/
[datastar]: https://data-star.dev/
[dramatiq]: https://dramatiq.io/
[jinja]: https://jinja.palletsprojects.com/en/stable/
[redis]: https://redis.io/
[starlette]: https://starlette.dev/
[sqlmodel]: https://sqlmodel.tiangolo.com/
[traefik]: https://traefik.io/


## Environment set up

Start by retrieving the sample datasets that have been made available by the
client. These are contained in the file

```ipma/2025-marine-data-catalog/sample-data/20251125_datasample01_restored_data.tar.gz```

which is available at the internal knowledge base platform (you should know how to retrieve it).

Create a base directory for the project's datasets (for example at `~/data/seis-lab-data`)
and then get the archive and extract it inside this directory:

```shell
mkdir -p ~/data/seis-lab-data
cd ~/data/seis-lab-data

# now get the tar archive into this dir and extract it
tar -xvf 20251125_datasample01_restored_data.tar.gz

# remove the archive after extraction
rm 20251125_datasample01_restored_data.tar.gz
```

You should get something that looks like this (this is an abbreviated listing):

```shell
ricardo@tygra:~/data/seis-lab-data/$ tree -L 4
.
└── prr_eolicas
    └── base-final
        └── surveys
            └── owf-2025
```

Now clone this repo locally:

```shell
cd ~/dev  # or wherever you want to store the code

git clone https://github.com/NaturalGIS/seis-lab-data.git
cd seis-lab-data
```

In order to simplify mounting the data directory inside docker services, the project assumes
there is a `sample-data` directory under the root of the repo. As such, make a symlink
pointing to the data directory you created above:

 ```shell
 # assuming your sample-data directory lives at `~/data/seis-lab-data`
 ln -s ~/data/seis-lab-data sample-data
 ```

Ensure you have installed [docker] and [uv] on your machine

Use `uv` to get the project installed locally.

```shell
uv sync --group dev --locked
```

Install the included [pre-commit] hooks:

```shell
uv run pre-commit install
```

Pull the project docker images from their respective registries. You will likely need to log in
to the `ghcr.io` registry.

```shell
docker compose -f docker/compose.dev.yaml pull
```

Then launch the stack:

```shell
docker compose -f docker/compose.dev.yaml up -d
```

You should now be able to access the webapp at

    http://localhost:8888

Please continue with the [bootstrapping](#bootstrapping-a-fresh-installation) section.


## Bootstrapping a fresh installation

The bootstrap process consists of:

- Creating/upgrading the database;
- Loading all default variables into the appropriate DB tables;
- Optionally adding some default projects, survey missions and survey-related records.

Bootstrapping is done by using the `seis-lab-data` CLI, which is available in the `webapp`
service. It contains many commands and can be called like this:

```shell
docker compose -f docker/compose.dev.yaml exec -ti webapp uv run seis-lab-data --help
```

Run the following commands:

```shell
# initialize the DB
docker compose -f docker/compose.dev.yaml exec -ti webapp uv run seis-lab-data db upgrade

# add default data
docker compose -f docker/compose.dev.yaml exec -ti webapp uv run seis-lab-data bootstrap all

# optionally, load sample records
docker compose -f docker/compose.dev.yaml exec -ti webapp uv run seis-lab-data dev load-all-samples

# also optionally, generate a large number of synthetic records
# (this is perhaps more useful when working on the web UI)
docker compose -f docker/compose.dev.yaml exec -ti webapp uv run seis-lab-data dev generate-many-projects --num-projects=50
```

## Additional notes

The docker image used for development uses docker's `latest` tag and is rebuilt whenever there are commits to the
repo's `main` branch. As such you should be sure to run

```shell
docker compose -f docker/compose.dev.yaml pull webapp
docker compose -f docker/compose.dev.yaml up -d
```

whenever you know there have been recent merges.


!!! note "Building the docker image locally"

    Most of the time you will be using a prebuilt docker image. However, there is a special case where you will need
    to build it locally. This case is when you add a new Python dependency to the project. In this case, build the
    image with:

    ```shell
    docker build \
      --tag ghcr.io/naturalgis/seis-lab-data/seis-lab-data:$(git branch --show-current) \
      --file docker/Dockerfile \
      .
    ```

    Then stand up the docker compose stack with:

    ```shell
    CURRENT_GIT_BRANCH=$(git branch --show-current) docker compose -f docker/compose.dev.yaml up -d --force-recreate
    ```

    [!NOTE]
    ### Getting translations to work correctly in your local dev environment

    Because the docker compose file used for dev bind mounts the entire `src` directory, it will
    mask the container's own compiled `*.mo` files. This means that after running
    `seis-lab-data translations compile` you need to restart the `webapp` service for the changes to take effect.


## Mounting the production archive locally

If needed, you can use sshfs to mount the production archive locally.

Install sshfs, then enable the `user_allow_other` option in the fuse config and you should be able to mount it locally.

```shell
apt install sshfs

# now edit /etc/fuse.conf and uncomment the line that has `user_allow_other`

mkdir <your-data-root>/production-archive

# this mounts the archive
sshfs <name-of-your-ssh-alias>:/mnt/seislab_data \
    <your-data-root>/production-archive \
    -o allow_other \
    -o reconnect \
    -o ServerAliveInterval=15

# now you must restart the docker compose stack in order for docker to be able to see the mount
docker compose -f docker/compose.dev.yaml up -d --force-recreate
```

You can later unmount it with:

```shell
fusermount -u <your-data-root>/production-archive
```


## Modifying the database

We are using [alembic](https://alembic.sqlalchemy.org/en/latest/) for tracking database modifications. This means that
all modifications to the database schema must be done through alembic migrations. In order to generate a new migration:

-   Perform whatever modifications you need to the database models in the code - these are located in
    `src/seis_labs_data/db/models.py`;

-   Ask alembic to autogenerate a suitable DB migration file by running a custom seis-lab-data CLI command:

    ```shell
    docker compose \
        -f docker/compose.dev.yaml \
        exec -ti webapp \
        uv run \
        seis-lab-data db generate-migration "short description of the migration"
    ```

-   Manually inspect the autogenerated file in order to check that it is correct and make any necessary modifications.
    Migration files are located in `src/seis_labs_data/migrations/versions/` and are named with a timestamp and a short
    description of the migration;

-   If the migration is correct, apply it to the database with:

    ```shell
    docker compose -f docker/compose.dev.yaml exec -ti webapp uv run seis-lab-data db migrate
    ```


## Auxiliary dev services

The development docker compose stack includes some additional relevant services:


##### dozzle

This is a dozzle instance, useful for monitoring the logs of the various services in the stack.
It is accessible at http://localhost:8888/monitoring


##### jupyter

This is a [jupyter](https://jupyter.org/) instance, useful for writing notebooks or interacting
with a Python REPL. It is accessible at http://localhost:5002


##### pg-admin

A [pg-admin](https://www.pgadmin.org/) instance, useful for inspecting the stack's databases.
It is accessible at http://pgadmin.localhost:8888 and login credentials are:

- user: `dev@dev.dev`
- password: `dev`


##### GeoNode (optional)

!!! note

    The GeoNode service is only meant for use during development, as the production environment will have
    an externally managed GeoNode as its target.

A [GeoNode](https://geonode.org/) v5.1.1 instance, used as the target for exporting survey-related
records. It is made up of several services (`geonode-db`, `geonode-django`, `geonode-celery`,
`geonode-nginx`, `geonode-geoserver` and `geonode-geoserver-data`). Its configuration lives in
`docker/geonode/geonode-dev.env`.

These services are resource-hungry, so they only start when the `geonode` compose profile is
active:

```shell
docker compose -f docker/compose.dev.yaml --profile geonode up -d
```

The first boot is slow, because GeoNode runs its DB migrations, loads fixtures and collects
static files.

- GeoNode is accessible at http://geonode.localhost:8888, with credentials `admin` / `admin123`
- GeoServer is accessible at http://geonode.localhost:8888/geoserver/, with credentials
  `admin` / `geoserver`
- Other services in the stack (e.g. `long-tasks-worker`) can reach the GeoNode API directly at
  `http://django:8000`
- uwsgi request logs are written to `/var/log/geonode.log` inside the `geonode-django` container

Exporting survey-related records to GeoNode is configured with these settings (exporting is
disabled when the URL is not set):

- `SEIS_LAB_DATA__TARGET_GEONODE__URL` - URL where the backend reaches the GeoNode API
- `SEIS_LAB_DATA__TARGET_GEONODE__PUBLIC_URL` - URL where users reach GeoNode, only needed if it
  differs from the previous one, as happens in the dev stack
- `SEIS_LAB_DATA__TARGET_GEONODE__USERNAME` and `SEIS_LAB_DATA__TARGET_GEONODE__PASSWORD` -
  credentials of the GeoNode user which seis-lab-data acts as, which becomes the owner of the
  exported resources. This is meant to be a service account, used only by seis-lab-data
- `SEIS_LAB_DATA__TARGET_GEONODE__CLIENT_ID` and `SEIS_LAB_DATA__TARGET_GEONODE__CLIENT_SECRET` -
  credentials of a GeoNode OAuth2 application, which must be _confidential_ and use the
  _resource owner password-based_ grant type. Each export exchanges the service account's
  credentials for an access token with it, revoking the token when done
- `SEIS_LAB_DATA__PUBLIC_URL` - must also be set for the workers, as exported GeoNode resources
  link back to their record's page

Exports run in the `exports` queue, consumed by the `long-tasks-worker` service. The dev stack already
sets all of these settings, using fixed credentials, the GeoNode counterparts of which can be
created with:

```shell
docker compose -f docker/compose.dev.yaml exec geonode-django python manage.py shell -c "
import os
from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model

Application = get_application_model()
user, _ = get_user_model().objects.get_or_create(
    username=os.environ['SLD_BOT_USERNAME'])
user.set_password(os.environ['SLD_BOT_PASSWORD'])
user.save()
Application.objects.update_or_create(
    client_id=os.environ['SLD_OAUTH_APP_CLIENT_ID'],
    defaults=dict(
        name=os.environ['SLD_OAUTH_APP_NAME'],
        user=user,
        client_secret=os.environ['SLD_OAUTH_APP_CLIENT_SECRET'],
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_PASSWORD,
    ),
)
"
```

After which the services that use them need to be recreated:

```shell
docker compose -f docker/compose.dev.yaml --profile geonode up -d
```


# Running tests

Normal tests can be run from inside the `webapp` compose container, after installing the required dependencies:

```shell
docker compose --file docker/compose.dev.yaml exec -ti webapp uv sync --locked --group gdal --group dev
docker compose --file docker/compose.dev.yaml exec -ti webapp uv run pytest
```

Integration tests can be run with the following incantation:

```shell
docker compose --file docker/compose.dev.yaml exec webapp uv run pytest -m integration
```

## End to end tests

End to end tests are run from outside the docker stack. They require that playwright is installed locally.
You can do this with:

```shell
uv run playwright install --with-deps chromium
```

Then tests can be run with:

```shell
uv run pytest \
    tests/e2e/ \
    -m e2e \
    --confcutdir tests/e2e \
    --user-email akadmin@email.com \
    --user-password admin123 \
    --base-url http://localhost:8888
```

The previous incantation will run all end to end tests in headless mode.
To run them in headed mode, you can use:

```shell
uv run pytest \
    tests/e2e/ \
    -m e2e \
    --confcutdir tests/e2e \
    --user-email akadmin@email.com \
    --user-password admin123 \
    --base-url http://localhost:8888 \
    --headed \
    --slowmo 1500
```


[docker]: https://www.docker.com/
[IPMA]: https://www.ipma.pt/pt/index.html
[pre-commit]: https://pre-commit.com/
[uv]: https://docs.astral.sh/uv/
[woodpecker]: https://woodpecker-ci.org/
