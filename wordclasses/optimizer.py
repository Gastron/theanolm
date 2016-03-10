#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import numpy

class Optimizer(object):
    """Word Class Optimizer
    """

    def __init__(self, num_classes, corpus_file, vocabulary_file = None):
        """Reads the vocabulary from the text ``corpus_file``. The vocabulary
        may be restricted by ``vocabulary_file``. Then reads the statistics from
        the text.
        """

        # Read the vocabulary.
        self.vocabulary = set(['<s>', '</s>', '<UNK>'])
        if vocabulary_file is None:
            for line in corpus_file:
                self.vocabulary.update(line.split())
        else:
            restrict_words = set(line.strip() for line in vocabulary_file)
            for line in corpus_file:
                for word in line.split():
                    if word in restrict_words:
                        self.vocabulary.add(word)

        # Create word IDs and read word statistics.
        self.vocabulary_size = len(self.vocabulary)
        self.word_ids = dict(zip(self.vocabulary, range(self.vocabulary_size)))
        corpus_file.seek(0)
        self._read_word_statistics(corpus_file)

        # Initialize classes and compute class statistics.
        self._freq_init_classes(num_classes)
        self._compute_class_statistics()

    def log_likelihood(self):
        """Computes the log likelihood that a bigram model would give to the
        corpus.
        """

        return (numpy.ma.log(self.cc_counts) * self.cc_counts).sum() + \
               (numpy.ma.log(self.word_counts) * self.word_counts).sum() - \
               2 * (numpy.ma.log(self.class_counts) * self.class_counts).sum()

    def _read_word_statistics(self, corpus_file):
        """Reads word statistics from corpus file.
        """

        self.word_counts = numpy.zeros(self.vocabulary_size, numpy.int64)
        # word-word counts
        self.ww_counts = numpy.zeros(
            (self.vocabulary_size, self.vocabulary_size), numpy.int64)

        for line in corpus_file:
            sentence = [self.word_ids['<s>']]
            for word in line.split():
                if word in self.vocabulary:
                    sentence.append(self.word_ids[word])
                else:
                    sentence.append(self.word_ids['<UNK>'])
            sentence.append(self.word_ids['</s>'])
            for word_id in sentence:
                self.word_counts[word_id] += 1
            for left_word_id, right_word_id in zip(sentence[:-1], sentence[1:]):
                self.ww_counts[left_word_id, right_word_id] += 1

    def _freq_init_classes(self, num_classes):
        """Initializes word classes based on word frequency.
        """

        self.num_classes = num_classes + 3

        self.word_to_class = [None] * self.vocabulary_size
        self.class_to_words = [set() for _ in range(self.num_classes)]

        self.word_to_class[self.word_ids['<s>']] = 0
        self.class_to_words[0].add(self.word_ids['<s>'])
        self.word_to_class[self.word_ids['</s>']] = 1
        self.class_to_words[1].add(self.word_ids['</s>'])
        self.word_to_class[self.word_ids['<UNK>']] = 2
        self.class_to_words[2].add(self.word_ids['<UNK>'])

        class_id = 3
        for word_id, _ in sorted(enumerate(self.word_counts),
                                 key=lambda x: x[1]):
            if not self.word_to_class[word_id] is None:
                # A class has been already assigned to <s>, </s>, and <UNK>.
                continue
            self.word_to_class[word_id] = class_id
            self.class_to_words[class_id].add(word_id)
            class_id = min((class_id + 1) % self.num_classes, 3)

    def _compute_class_statistics(self):
        """Computes class statistics.
        """

        self.class_counts = numpy.zeros(self.num_classes, numpy.int64)
        # class-class counts
        self.cc_counts = numpy.zeros(
            (self.num_classes, self.num_classes), numpy.int64)
        # class-word counts
        self.cw_counts = numpy.zeros(
            (self.num_classes, self.vocabulary_size), numpy.int64)
        # word-class counts
        self.wc_counts = numpy.zeros(
            (self.vocabulary_size, self.num_classes), numpy.int64)

        for word_id, class_id in enumerate(self.word_to_class):
            self.class_counts[class_id] += self.word_counts[word_id]
        for (left_word_id, right_word_id), count in numpy.ndenumerate(self.ww_counts):
            left_class_id = self.word_to_class[left_word_id]
            right_class_id = self.word_to_class[right_word_id]
            self.cc_counts[left_class_id,right_class_id] += count
            self.cw_counts[left_class_id,right_word_id] += count
            self.wc_counts[left_word_id,right_class_id] += count
    
    def _ll_change(self, old_count, new_count):
        result = 0
        if old_count != 0:
            result -= old_count * numpy.log(old_count)
        if new_count != 0:
            result += new_count * numpy.log(new_count)
        return result

    def _evaluate_move(self, word_id, new_class_id):
        """Evaluates how much moving a word to another class would change the
        log likelihood.
        """

        old_class_id = self.word_to_class[word_id]

        # old class
        old_count = self.class_counts[old_class_id]
        new_count = old_count - self.word_counts[word_id]
        result = 2 * old_count * numpy.log(old_count)
        result -= 2 * new_count * numpy.log(new_count)

        # new class
        old_count = self.class_counts[new_class_id]
        new_count = old_count + self.word_counts[word_id]
        result += 2 * old_count * numpy.log(old_count)
        result -= 2 * new_count * numpy.log(new_count)

        for iter_class_id, iter_wc_count in self.wc_counts[word_id,:]:
            if iter_class_id == old_class_id:
                continue
            if iter_class_id == new_class_id:
                continue

            # old class, class X
            old_count = self.cc_counts[old_class_id,iter_class_id]
            new_count = old_count - iter_wc_count
            result += self._ll_change(old_count, new_count)

            # new class, class X
            old_count = self.cc_counts[new_class_id,iter_class_id]
            new_count = old_count + iter_wc_count
            result += self._ll_change(old_count, new_count)

        for iter_class_id, iter_cw_count in self.cw_counts[:,word_id]:
            if iter_class_id == old_class_id:
                continue
            if iter_class_id == new_class_id:
                continue

            # class X, old class
            old_count = self.cc_counts[iter_class_id,old_class_id]
            new_count = old_count - iter_cw_count
            result += self._ll_change(old_count, new_count)

            # class X, new class
            old_count = self.cc_counts[iter_class_id,new_class_id]
            new_count = old_count + iter_cw_count
            result += self._ll_change(old_count, new_count)

        # old class, new class
        old_count = self.cc_counts[old_class_id,new_class_id]
        new_count = old_count - \
                    self.wc_counts[word_id,new_class_id] + \
                    self.cw_counts[old_class_id,word_id] - \
                    self.ww_counts[word_id,word_id]
        result += self._ll_change(old_count, new_count)

        # new class, old class
        old_count = self.cc_counts[new_class_id,old_class_id]
        new_count = old_count - \
                    self.cw_counts[new_class_id,word_id] + \
                    self.wc_counts[word_id,old_class_id] - \
                    self.ww_counts[word_id,word_id]
        result += self._ll_change(old_count, new_count)

        # old class, old class
        old_count = self.cc_counts[old_class_id,old_class_id]
        new_count = old_count - \
                    self.wc_counts[word_id,old_class_id] - \
                    self.cw_counts[old_class_id,word_id] + \
                    self.ww_counts[word_id,word_id]
        result += self._ll_change(old_count, new_count)

        # new class, new class
        old_count = self.cc_counts[new_class_id,new_class_id]
        new_count = old_count + \
                    self.wc_counts[word_id,new_class_id] + \
                    self.cw_counts[new_class_id,word_id] + \
                    self.ww_counts[word_id,word_id]
        result += self._ll_change(old_count, new_count)

        return result

    def _move(self, word_id, new_class_id):
        """Moves a word to another class.
        """

        old_class_id = self.word_to_class[word_id]
        word_count = self.word_counts[word_id]
        self.class_counts[old_class_id] -= word_count
        self.class_counts[new_class_id] += word_count
        
        for right_word_id, count in enumerate(self.ww_counts[word_id,:]):
            if right_word_id == word_id:
                continue
            right_class_id = self.word_to_class[right_word_id]
            self.cc_counts[old_class_id,right_class_id] -= count
            self.cc_counts[new_class_id,right_class_id] += count
            self.cw_counts[old_class_id,right_word_id] -= count
            self.cw_counts[new_class_id,right_word_id] += count
        
        for left_word_id, count in enumerate(self.ww_counts[:,word_id]):
            if left_word_id == word_id:
                continue
            left_class_id = self.word_to_class[left_word_id]
            self.cc_counts[left_class_id,old_class_id] -= count
            self.cc_counts[left_class_id,new_class_id] += count
            self.wc_counts[left_word_id,old_class_id] -= count
            self.wc_counts[left_word_id,new_class_id] += count

        count = self.ww_counts[word_id,word_id]
        self.cc_counts[old_class_id,old_class_id] -= count
        self.cc_counts[new_class_id,new_class_id] += count
        self.cw_counts[old_class_id,word_id] -= count
        self.cw_counts[new_class_id,word_id] += count
        self.wc_counts[word_id,old_class_id] -= count
        self.wc_counts[word_id,new_class_id] += count

        self.class_to_words[old_class_id].remove(word_id)
        self.class_to_words[new_class_id].add(word_id)
        self.word_to_class[word_id] = new_class_id
