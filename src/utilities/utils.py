import logging
import os
from itertools import groupby, product
from logging import FileHandler, LogRecord

import mlflow
import pandas as pd
import collections


def top_scores(predictions, n):
    top_n_scores = pd.DataFrame()
    for u in list(set(predictions['users'])):
        p = predictions.loc[predictions['users'] == u]
        top_n_scores = top_n_scores.append(p.head(n))
    return top_n_scores


def nested_dict_update(d, u):
    """
    Dictionary update suitable for nested dictionary
    :param d: original dict
    :param u: dict from where updates are taken
    :return: Updated dictionary
    """
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = nested_dict_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def linearize(dictionary):
    """
    Linearize a nested dictionary making keys, tuples
    :param dictionary: nested dict
    :return: one level dict
    """
    exps = []
    for key, value in dictionary.items():
        if isinstance(value, collections.abc.Mapping):
            exps.extend(((key, lin_key), lin_value) for lin_key, lin_value in linearize(value))
        elif isinstance(value, list):
            exps.append((key, value))
        else:
          raise ValueError("Only dict or lists!!!")
    return exps


def extract(elem: tuple):
    """
    Exctract the element of a single element tuple
    :param elem: tuple
    :return: element of the tuple if singleton or the tuple itself
    """
    if len(elem) == 1:
        return elem[0]
    return elem


def delinearize(lin_dict):
    """
    Convert a dictionary where tuples can be keys in na nested dictionary
    :param lin_dict: dicionary where keys can be tuples
    :return:
    """
    # Take keys that are tuples
    filtered = list(filter(lambda x: isinstance(x[0], tuple), lin_dict.items()))
    # Group it to make one level
    grouped = groupby(filtered, lambda x: x[0][0])
    # Create the new dict and apply recursively
    new_dict = {k: delinearize({extract(elem[0][1:]): elem[1] for elem in v}) for k, v in grouped}
    # Remove old items and put new ones
    for key, value in filtered:
        lin_dict.pop(key)
    delin_dict = {**lin_dict, **new_dict}
    return delin_dict


def make_grid(dict_of_list):
    """
    Produce a list of dict for each combination of values in the input dict given by the list of values
    :param dict_of_list: a dictionary where values can be lists
    :return: a list of dictionaries given by the cartesian product of values in the input dictionary
    """
    # Linearize the dict to make the cartesian product straight forward
    linearized_dict = linearize(dict_of_list)
    # Compute the grid
    keys, values = zip(*linearized_dict)
    grid_dict = list(dict(zip(keys, values_list)) for values_list in product(*values))
    # Delinearize the list of dicts
    return [delinearize(dictionary) for dictionary in grid_dict]


class FlushFileHandler(FileHandler):
    def emit(self, record: LogRecord) -> None:
        super().emit(record)
        self.flush()


def setup_mlflow(exp_name, mlflow_path):
    """
    Setup a MLflow experiments suite.

    :param exp_name: The experiment suite's name.
    :param mlflow_path: The path where to store all experiments results.
    :return: The eperiment path with respect to the experiment suite's name.
    """
    mlflow.tensorflow.autolog()
    os.makedirs(mlflow_path, exist_ok=True)
    os.makedirs(os.path.join(mlflow_path, '.trash'), exist_ok=True)

    experiment = mlflow.get_experiment_by_name(exp_name)
    if not experiment:
        exps = os.listdir(mlflow_path)
        exps.pop(exps.index('.trash'))
        if len(exps) == 0:
            exp_id = '0'
        else:
            exp_id = str(max([int(exp) for exp in exps]) + 1)
        exp_path = mlflow_path + '/' + exp_id
        experiment_id = mlflow.create_experiment(
            exp_name, artifact_location='file:' + exp_path)
    else:
        experiment_id = experiment.experiment_id
        exp_path = experiment.artifact_location.split(':')[1]
    mlflow.set_experiment(experiment_id=experiment_id)
    return exp_path


def mlflow_linearize(dictionary):
    """
    Linearize a nested dictionary concatenating keys in order to allow mlflow parameters recording.

    :param dictionary: nested dict
    :return: one level dict
    """
    exps = {}
    for key, value in dictionary.items():
        if isinstance(value, collections.abc.Mapping):
            exps = {**exps,
                    **{key + '.' + lin_key: lin_value for lin_key, lin_value in mlflow_linearize(value).items()}}
        else:
            exps[key] = value
    return exps


def get_experiment_logger(destination_folder):
    """
    Get the logger required for the Experimenter.

    :param destination_folder: folder where to save the log
    :return: logger
    """
    # Instantiate the formatted and force-flush file handler
    formatter = logging.Formatter('%(asctime)s %(message)s', '[%H:%M:%S]')
    file_handler = FlushFileHandler(os.path.join(destination_folder, 'log.txt'))
    file_handler.setFormatter(formatter)

    # Instantiate the logger
    logger = logging.getLogger('callback')
    for handler in logger.handlers:  # Delete all the current handlers
        logger.removeHandler(handler)
    logger.addHandler(file_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # Do not write also on stdout (i.e. don't propagate to upper-level logger)
    return logger
