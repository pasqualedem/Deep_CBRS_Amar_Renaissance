import abc

from spektral.layers import GCNConv, GraphSageConv, GATConv
from tensorflow.keras import models, regularizers

from layers.dgcf_conv import DGCFConv
from layers.lightgcn_conv import LightGCNConv
from models.gnn import SequentialGNN, HalfInputSequentialGNN


class TwoStepGNN(abc.ABC, models.Model):
    def __init__(
        self,
        n_users,
        n_items,
        adj_matrices,
        n_hops,
        embedding_dim=8,
        item_node="mean",
        final_node="concatenation",
        dropout=None,
        l2_regularizer=None,
        cache_neighbours=False,
        **kwargs
    ):
        """
        Initialize a Basic recommender system based on Graph Neural Networks (GCN).

        :param adj_matrix: The graph adjacency matrix. It can be either sparse or dense.
        :param n_hops: Distance from which every node will be convoluted to.
        :param embedding_dim: The dimension of latent features representations of user and items.
        :param final_node: Defines how the final node will be represented from layers. One between the following:
                           'concatenation', 'sum', 'mean', 'w-sum', 'last'.
        :param dropout: The dropout to apply after each GCN layer. It can be None.
        :param l2_regularizer: L2 factor to apply on embeddings and GCN layers' weights. It can be None.
        :param cache_neighbours: Whether to pre-compute and cache the neighbours of each node. This is useful only
                                 if the adjacency matrix is very sparse and n_hops is relatively small.
        :param **kwargs: Additional args not used.
        """
        super().__init__()

        # Instantiate the regularizer
        if l2_regularizer is not None:
            regularizer = regularizers.l2(l2_regularizer)
        else:
            regularizer = None

        if len(adj_matrices) != 2:
            raise ValueError('Exactly two adjacency matrix are needed!')
        adj_ui_matrix, adj_kg_matrix = adj_matrices

        # Build the first sequential GNN model
        gnn_kwargs = {'regularizer': regularizer}
        step_one_gnn_layers = [self.build_gnn_layer(i, **gnn_kwargs) for i in range(n_hops)]
        self.step_one_gnn_layers = SequentialGNN(
            adj_kg_matrix, step_one_gnn_layers,
            embedding_dim=embedding_dim, final_node=item_node,
            dropout=dropout, regularizer=regularizer, cache_neighbours=cache_neighbours
        )

        # Get the slice of item embeddings
        self.n_embeddings = n_items

        # Build the second sequential model
        # Get the number of hiddens for the second GNN
        if hasattr(self, 'n_hiddens'):
            if n_hops == len(self.n_hiddens):
                if item_node == 'concatenation':
                    second_embedding_dim = embedding_dim * (n_hops + 1)
                    self.n_hiddens.extend([second_embedding_dim for _ in range(n_hops)])
                else:
                    self.n_hiddens.extend([embedding_dim for _ in range(n_hops)])
                    second_embedding_dim = embedding_dim
        else:
            second_embedding_dim = embedding_dim
        step_two_gnn_layers = [self.build_gnn_layer(i + n_hops, **gnn_kwargs) for i in range(n_hops)]
        self.step_two_gnn_layers = HalfInputSequentialGNN(
            adj_ui_matrix, step_two_gnn_layers, n_users,
            embedding_dim=second_embedding_dim, final_node=final_node,
            dropout=dropout, cache_neighbours=cache_neighbours
        )

    @abc.abstractmethod
    def build_gnn_layer(self, i, **kwargs):
        """
        Abstract method that builds the i-th GNN layer.

        :param i: The index.
        :param kwargs: Additional parameters.
        """
        pass

    def call(self, inputs, **kwargs):
        x = self.step_one_gnn_layers(None)
        return self.step_two_gnn_layers(x[:self.n_embeddings])


class TwoStepGCN(TwoStepGNN):
    def __init__(
            self,
            n_users,
            n_items,
            adj_matrices,
            n_hiddens=(8, 8, 8),
            **kwargs
    ):
        """
        Initialize a Basic recommender system based on Two Step Graph Convolutional Networks (GCN).

        :param adj_matrix: The graph adjacency matrix. It can be either sparse or dense.
        :param n_hiddens: A sequence of numbers of hidden units for each GCN layer.
        """
        self.n_hiddens = n_hiddens

        # Note normalizing the adjacency matrix using the GCN filter
        adj_matrices = [GCNConv.preprocess(matrix) for matrix in adj_matrices]
        super().__init__(
            n_users,
            n_items,
            adj_matrices,
            len(n_hiddens),
            **kwargs)

    def build_gnn_layer(self, i, regularizer=None, **kwargs):
        return GCNConv(
            self.n_hiddens[i],
            activation='relu',
            kernel_regularizer=regularizer,
            bias_regularizer=regularizer
        )


class TwoStepGraphSage(TwoStepGNN):
    def __init__(
            self,
            n_users,
            n_items,
            adj_matrices,
            n_hiddens=(8, 8, 8),
            aggregate='mean',
            **kwargs
    ):
        """
        Initialize TwoStepGraphSage.

        :param adj_matrix: The graph adjacency matrix. It can be either sparse or dense.
        :param n_hiddens: A sequence of numbers of hidden units for each GraphSage layer.
        :param aggregate: Which aggregation function to use in update (mean, max, ...)
        """
        self.n_hiddens = n_hiddens
        self.aggregate = aggregate

        super().__init__(
            n_users,
            n_items,
            adj_matrices,
            len(n_hiddens),
            **kwargs)

    def build_gnn_layer(self, i, regularizer=None, **kwargs):
        return GraphSageConv(
            self.n_hiddens[i],
            activation='relu',
            aggregate=self.aggregate,
            kernel_regularizer=regularizer,
            bias_regularizer=regularizer
        )


class TwoStepGAT(TwoStepGNN):
    def __init__(
            self,
            n_users,
            n_items,
            adj_matrix,
            n_hiddens=(8, 8, 8),
            dropout_rate=0.0,
            **kwargs
    ):
        """
        Initialize a TwoStep Graph Attention Networks (GAT).

        :param adj_matrix: The graph adjacency matrix. It can be either sparse or dense.
        :param n_hiddens: A sequence of numbers of hidden units for each GAT layer.
        :param dropout_rate: The dropout rate to apply to the attention coefficients in GAT.
        """
        self.n_hiddens = n_hiddens
        self.dropout_rate = dropout_rate

        super().__init__(
            n_users,
            n_items,
            adj_matrix,
            len(n_hiddens),
            **kwargs)

    def build_gnn_layer(self, i, regularizer=None, **kwargs):
        return GATConv(
            self.n_hiddens[i],
            dropout_rate=self.dropout_rate,
            activation='relu',
            kernel_regularizer=regularizer,
            bias_regularizer=regularizer
        )


class TwoStepLightGCN(TwoStepGNN):
    def __init__(
            self,
            n_users,
            n_items,
            adj_matrix,
            n_layers=3,
            **kwargs
    ):
        """
        Initialize a TwoStep LigthGCN.

        :param adj_matrix: The graph adjacency matrix. It can be either sparse or dense.
        :param n_layers: The number of sequential LightGCN layers.
        """
        # Override final_node parameter to 'mean'
        kwargs['final_node'] = 'mean'

        # Note normalizing the adjacency matrix using the GCN filter
        adj_matrix = [LightGCNConv.preprocess(matrix ) for matrix in adj_matrix]
        super().__init__(
            n_users,
            n_items,
            adj_matrix,
            n_layers,
            **kwargs)

    def build_gnn_layer(self, i, **kwargs):
        return LightGCNConv()


class TwoStepDGCF(TwoStepGNN):
    def __init__(
            self,
            n_users,
            n_items,
            adj_matrix,
            n_layers=3,
            **kwargs
    ):
        """
        Initialize DGCF.

        :param adj_matrix: The graph adjacency matrix. It can be either sparse or dense.
        :param n_layers: The number of sequential DGCF layers.
        """
        # Override final_node parameter to 'mean'
        kwargs['final_node'] = 'mean'

        # Note normalizing the adjacency matrix using the GCN filter and getting the crosshop matrix
        crosshop_matrix = [DGCFConv.preprocess(matrix) for matrix in adj_matrix]
        super().__init__(
            n_users,
            n_items,
            crosshop_matrix,
            n_layers,
            **kwargs)

    def build_gnn_layer(self, i, regularizer=None, **kwargs):
        return DGCFConv(regularizer)