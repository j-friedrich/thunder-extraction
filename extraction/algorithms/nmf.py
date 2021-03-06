from numpy import clip, inf, percentile, asarray, where, size, prod, unique
from scipy.ndimage import median_filter
from sklearn.decomposition import NMF as SKNMF
from skimage.measure import label
from skimage.morphology import remove_small_objects
import itertools

from regional import one, many
from ..model import ExtractionModel
from ..utils import check_images

class NMF(object):
  """
  Source extraction using local non-negative matrix factorization.
  """
  def __init__(self, k=5, max_iter=20, max_size='full', min_size=20, percentile=95, overlap=0.1):
      self.k = k
      self.max_iter = max_iter
      self.min_size = min_size
      self.max_size = max_size
      self.overlap = overlap
      self.percentile = percentile

  def fit(self, images, block_size=None):
      images = check_images(images)
      block_size = block_size if block_size is not None else images.shape[1:]
      blocks = images.toblocks(size=block_size)
      shape = blocks.blockshape
      sources = blocks.tordd().map(lambda kv: self._get(kv[0], kv[1], shape))
      collected = sources.collect()
      return ExtractionModel(many(list(itertools.chain.from_iterable(collected))))

  def _get(self, index, block, shape):

      offset = (asarray(index[1]) * asarray(shape))[1:]
      dims = block.shape[1:]
      max_size = prod(dims) / 2 if self.max_size == 'full' else self.max_size

      # reshape to t x spatial dimensions
      data = block.reshape(block.shape[0], -1)

      # build and apply NMF model to block
      model = SKNMF(self.k, max_iter=self.max_iter)
      model.fit(clip(data, 0, inf))

      # reconstruct sources as spatial objects in one array
      components = model.components_.reshape((self.k,) + dims)

      # convert from basis functions into shape
      # by median filtering (optional), applying a percentile threshold,
      # finding connected components and removing small objects
      combined = []
      for component in components:
          tmp = component > percentile(component, self.percentile)
          regions = remove_small_objects(label(tmp), min_size=self.min_size)
          ids = unique(regions)
          ids = ids[ids > 0]
          for ii in ids:
              r = regions == ii
              r = median_filter(r, 2)
              coords = asarray(where(r)).T + offset
              if (size(coords) > 0) and (size(coords) < max_size):
                  combined.append(one(coords))

      # merge overlapping sources
      if self.overlap is not None:

          # iterate over source pairs and find a pair to merge
          def merge(sources):
              for i1, s1 in enumerate(sources):
                  for i2, s2 in enumerate(sources[i1+1:]):
                      if s1.overlap(s2) > self.overlap:
                          return i1, i1 + 1 + i2
              return None

          # merge pairs until none left to merge
          pair = merge(combined)
          testing = True
          while testing:
              if pair is None:
                  testing = False
              else:
                  combined[pair[0]] = combined[pair[0]].merge(combined[pair[1]])
                  del combined[pair[1]]
                  pair = merge(combined)

      return combined