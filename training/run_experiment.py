"""Script to run experiments."""
from datetime import datetime
import importlib
from pathlib import Path
from typing import List, Optional, Type
import warnings

warnings.filterwarnings("ignore")

import hydra
from loguru import logger
from omegaconf import DictConfig, OmegaConf
import pytorch_lightning as pl
from torch import nn
from tqdm import tqdm
import wandb


LOGS_DIRNAME = Path(__file__).parent.resolve() / "logs"


def _create_experiment_dir(config: DictConfig) -> Path:
    """Creates log directory for experiment."""
    log_dir = (
        LOGS_DIRNAME
        / f"{config.model.type}_{config.network.type}".lower()
        / datetime.now().strftime("%m%d_%H%M%S")
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _save_config(config: DictConfig, log_dir: Path) -> None:
    """Saves config to log directory."""
    with (log_dir / "config.yaml").open("w") as f:
        OmegaConf.save(config=config, f=f)


def _configure_logging(log_dir: Optional[Path], level: str) -> None:
    """Configure the loguru logger for output to terminal and disk."""
    # Remove default logger to get tqdm to work properly.
    logger.remove()
    logger.add(lambda msg: tqdm.write(msg, end=""), colorize=True, level=level)
    if log_dir is not None:
        logger.add(
            str(log_dir / "train.log"),
            format="{time:YYYY-MM-DD at HH:mm:ss} | {level} | {message}",
        )


def _import_class(module_and_class_name: str) -> type:
    """Import class from module."""
    module_name, class_name = module_and_class_name.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def _configure_callbacks(callbacks: DictConfig,) -> List[Type[pl.callbacks.Callback]]:
    """Configures lightning callbacks."""
    pl_callbacks = [
        getattr(pl.callbacks, callback.type)(**callback.args)
        for callback in callbacks.values()
    ]
    return pl_callbacks


def _configure_logger(
    network: Type[nn.Module], config: DictConfig, log_dir: Path
) -> Type[pl.loggers.LightningLoggerBase]:
    """Configures lightning logger."""
    if config.trainer.wandb:
        logger.info("Logging model with W&B")
        pl_logger = pl.loggers.WandbLogger(save_dir=str(log_dir))
        pl_logger.watch(network)
        pl_logger.log_hyperparams(vars(config))
        return pl_logger
    logger.info("Logging model with Tensorboard")
    return pl.loggers.TensorBoardLogger(save_dir=str(log_dir))


def _save_best_weights(
    pl_callbacks: List[Type[pl.callbacks.Callback]], use_wandb: bool
) -> None:
    """Saves the best model."""
    model_checkpoint_callback = next(
        callback
        for callback in pl_callbacks
        if isinstance(callback, pl.callbacks.ModelCheckpoint)
    )
    best_model_path = model_checkpoint_callback.best_model_path
    if best_model_path:
        logger.info(f"Best model saved at: {best_model_path}")
        if use_wandb:
            logger.info("Uploading model to W&B...")
            wandb.save(best_model_path)


def _load_lit_model(
    lit_model_class: type, network: Type[nn.Module], config: DictConfig
) -> Type[pl.LightningModule]:
    """Load lightning model."""
    if config.load_checkpoint is not None:
        logger.info(
            f"Loading network weights from checkpoint: {config.load_checkpoint}"
        )
        return lit_model_class.load_from_checkpoint(
            config.load_checkpoint,
            network=network,
            optimizer=config.optimizer,
            criterion=config.criterion,
            lr_scheduler=config.lr_scheduler,
            **config.model.args,
        )
    return lit_model_class(
        network=network,
        optimizer=config.optimizer,
        criterion=config.criterion,
        lr_scheduler=config.lr_scheduler,
        **config.model.args,
    )


def run(config: DictConfig) -> None:
    """Runs experiment."""
    log_dir = _create_experiment_dir(config)
    _configure_logging(log_dir, level=config.logging)
    logger.info("Starting experiment...")

    pl.utilities.seed.seed_everything(config.trainer.seed)

    # Load classes.
    data_module_class = _import_class(f"text_recognizer.data.{config.dataset.type}")
    network_class = _import_class(f"text_recognizer.networks.{config.network.type}")
    lit_model_class = _import_class(f"text_recognizer.models.{config.model.type}")

    # Initialize data object and network.
    data_module = data_module_class(**config.dataset.args)
    network = network_class(**data_module.config(), **config.network.args)

    # Load callback and logger.
    pl_callbacks = _configure_callbacks(config.callbacks)
    pl_logger = _configure_logger(network, config, log_dir)

    # Load ligtning model.
    lit_model = _load_lit_model(lit_model_class, network, config)

    # Save config to experiment dir.
    _save_config(config, log_dir)

    trainer = pl.Trainer(
        **config.trainer.args,
        callbacks=pl_callbacks,
        logger=pl_logger,
        weights_save_path=str(log_dir),
    )

    if config.trainer.args.fast_dev_run:
        logger.info("Fast development run...")
        trainer.fit(lit_model, datamodule=data_module)
        return None

    if config.trainer.tune:
        logger.info("Tuning learning rate and batch size...")
        trainer.tune(lit_model, datamodule=data_module)

    if config.trainer.train:
        logger.info("Training network...")
        trainer.fit(lit_model, datamodule=data_module)

    if config.trainer.test:
        logger.info("Testing network...")
        trainer.test(lit_model, datamodule=data_module)

    _save_best_weights(pl_callbacks, config.trainer.wandb)


@hydra.main(config_path="conf", config_name="config")
def main(config: DictConfig) -> None:
    """Loads config with hydra."""
    print(OmegaConf.to_yaml(config))
    run(config)


if __name__ == "__main__":
    main()
