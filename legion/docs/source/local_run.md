# Local run (local model execution)

In order to run model in environment that is similar to train and execution environments Legion Platform provides you `legionctl create-sandbox` command that can create docker container with preinstalled requirements.

## Prerequirements
* Linux based system with bash (at least version 4)
* Docker engine (at least version 17.0) with access from current user (`docker ps` should executes without errors)
* Python 3.6

## How to run?
1. Firstly, you have to install `legion` package from PyPi (you may do this in the dedicated environment, created by pipenv, for example).

```bash
pip install legion
```
2. Then, you have to run `legionctl create-sandbox` command that will create `legion-activate.sh` script **in the your current directory**.

```bash
legionctl create-sandbox
```
You may override default parameters using CLI arguments or environment variables (priority order is CLI arguments / environment variables / default values)

`--image` - docker image (named Legion Toolchain) from which container will be started.

Should be compatible with Legion Platform. By default Legion Platform provides **legionplatform/python-toolchain** public image. Also can be set using `LEGION_TOOLCHAIN` environment variable.

Example of value: `docker-registry-host:900/legion/base-python-image:0.9.1`

3. Activate Legion environment (go inside docker container)

```bash
./legion-activate.sh
```

Execution of this command starts temporarly docker container (will be removed on exit) with mounting actual working directory to `/work-directory` path inside container.

4. Run your training scripts

Inside container's shell (bash) you may run your python code (using `python3` command), run your notebooks (using `jupyter nbconver --execute` command), run Jupyter notebook server (that will be accessible from your machine) or run other commands.

Your code may use `legion` python package to generate Legion Platform model binaries using `legion.model` API.

At the end of your pipeline you have to export and save your models (using `legion.model.export(....)` and `legion.model.save()` commands)

5. Build model images

```bash
legionctl build
```

To build model images you have to run command above. It will self-capture current container with all installed dependecies, add additional packages (as a nginx webserver) and persist it on your machine's docker engine as a new image.

Name of image will be printed in the console.

## How to use with Jupyter Notebook?
You are free to run jupyter notebook (that is installed by default) inside development container.
Only one concern is to add `--no-browser --allow-root` arguments.

Here is an example of command
```bash
jupyter notebook --no-browser --allow-root
```

## Debugging
To debug your applications you may use next debugging protocols:
* [PyDevd](https://pypi.org/project/pydevd/) that is supported in PyCharm Professional, PyDev, VSCode Python
* [ptvsd](https://pypi.org/project/ptvsd/) that is supported in VSCode

## PyDevd
PyDevd debugging works in a **client (in your code) - server (in IDE)** way through network connection.

To start debugging you have to:
1. Start debugging server in your IDE.
2. Run `legion-activate.sh` with environment variables `PYDEVD_HOST` and `PYDEVD_PORT`.

Example:
```bash
PYDEVD_HOST=127.0.0.1 PYDEVD_PORT=8090 ./legion-activate.sh
```

### How to configure debugging using PyDevd in PyCharm
TBD

## ptvsd
**ptvsd** is a editor that has been developed dedicated for VSCode IDE. It works in a **server (in your code) - client (in IDE) way** through network connection. Your python application starts dedicated thread in which it server attach requests of debugger.

To start debugging you have to:
1. Configure attaching in your IDE, choose port (for example 8000)
2. Run `legion-activate.sh` with environment variables `PTVSD_PORT`, `PTVSD_HOST` and `PTVSD_WAIT_ATTACH` (`PTVSD_HOST` and `PTVSD_WAIT_ATTACH` are optional, by default `PTVSD_HOST=0.0.0.0` and `PTVSD_WAIT_ATTACH=0`).

Example:
```bash
PTVSD_PORT=8000 ./legion-activate.sh
```

### How to configure debugging using ptvsd in VsCode
1. Open debugging tab
2. Click on gear icon
3. Add next configuration
```json
{
    "name": "Attach ",
    "type": "python",
    "request": "attach",
    "port": 8000, // Choosen debugging port
    "host": "localhost",
    "pathMappings": [
        {
            "localRoot": "${workspaceFolder}",
            "remoteRoot": "/work-directory"
        }
    ],
    "redirectOutput": false
},
```
4. Run `./legion-activate.sh` with `PTVSD_*` environment variables.
5. Run debugging configuration

## Example of usage
```bash
# Go to project directory
host> cd /my-ml-project

# Install legion CLI tools and python package
host> sudo pip3 install legion

# Create sandbox
host> legionctl create-sandbox

# Go inside sandbox
host> ./legion-activate.sh

# Run Jupyter notebook server
sandbox> jupyter notebook --no-browser --allow-root

# ... do actions inside Jupyter web console
# ... execute legion.model.save() inside Jupyter web console

# Create model's image
sandbox> legionctl build

# Run builded docker container (ON HOST MACHINE)
host> docker run --rm -p 5000:5000 61bdddad33ea

# ... test model API using web-browser / Postman / wget

# Exit from container and terminate machine
sandbox> exit
```

