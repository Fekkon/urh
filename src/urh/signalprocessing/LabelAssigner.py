import copy
from collections import defaultdict

from urh import constants
from urh.signalprocessing.Interval import Interval
from urh.signalprocessing.ProtocoLabel import ProtocolLabel


class LabelAssigner(object):
    def __init__(self, blocks):
        """

        :type blocks: list of ProtocolBlock
        """
        self.__blocks = blocks
        self.preamble_end = 0
        self.constant_intervals = defaultdict(set)
        self.constant_intervals_per_block = defaultdict(list)

    @property
    def is_initialized(self):
        return len(self.constant_intervals) > 0 if len(self.__blocks) > 0 else True

    def find_preamble(self) -> ProtocolLabel:
        preamble_ends = list()

        for block in self.__blocks:
            # searching preamble
            preamble_end = block.find_preamble_end()
            if preamble_end is None or preamble_end < 1:
                continue
            preamble_ends.append(preamble_end)

        if len(preamble_ends) == 0:
            return None

        self.preamble_end = max(preamble_ends, key=preamble_ends.count)
        return ProtocolLabel(name="Preamble", start=0, end=self.preamble_end-1, val_type_index=0, color_index=None)

    def __find_constant_intervals(self):
        self.constant_intervals.clear()
        self.constant_intervals_per_block.clear()

        for i in range(0, len(self.__blocks)):
            for j in range(i + 1, len(self.__blocks)):
                range_start = 0
                constant_length = 0
                bits_i = self.__blocks[i].decoded_bits_str[self.preamble_end:]
                bits_j = self.__blocks[j].decoded_bits_str[self.preamble_end:]
                end = min(len(bits_i), len(bits_j)) - 1

                for k, (bit_i, bit_j) in enumerate(zip(bits_i, bits_j)):
                    if bit_i == bit_j:
                        constant_length += 1
                    else:
                        if constant_length > constants.SHORTEST_CONSTANT_IN_BITS:
                            interval = Interval(self.preamble_end+range_start, self.preamble_end+k-1)
                            self.constant_intervals[(i,j)].add(interval)
                            self.constant_intervals_per_block[i].append(interval)
                            self.constant_intervals_per_block[j].append(interval)

                        constant_length = 0
                        range_start = k + 1

                if constant_length > constants.SHORTEST_CONSTANT_IN_BITS:
                    interval = Interval(self.preamble_end+range_start, self.preamble_end+ end)
                    self.constant_intervals[(i,j)].add(interval)
                    self.constant_intervals_per_block[i].append(interval)
                    self.constant_intervals_per_block[j].append(interval)


        # Combine intervals
        # combined_indices = dict()
        # for block_index, intervals in self.constant_intervals.items():
        #     combined_intervals = list()
        #     for interval in sorted(intervals):
        #         last_interval = None if len(combined_intervals) == 0 else combined_intervals[-1]
        #         if last_interval and last_interval.overlaps_with(interval):
        #             combined_intervals.remove(last_interval)
        #             combined_intervals.append(last_interval.find_common_interval(interval))
        #         else:
        #             combined_intervals.append(interval)
        #
        #         combined_indices[block_index] = combined_intervals

        # Apply a label for each constant range
        # if labels overlap, there are different merge strategies
            # 1) choose the range that occurred most frequently
            # 2) split the overlapping ranges and create two labels -> not good as this changes the information
            # 3) Use the smallest common range (hides possible informations/broken protocols shrink information range)
        # when to create a new labelset?
           # 1) use information about diffs like (0, 2) [71-87, 135-155] 8070 00010 and put blocks in labelset
            #  if they have enough in common

        # for block_index in sorted(self.constant_intervals_per_block):
        #     interval_info = ""
        #     for interval in sorted(set(self.constant_intervals_per_block[block_index])):
        #         interval_info += str(interval) + " (" + str(self.constant_intervals_per_block[block_index].count(interval)) + ") "
        #
        #     print(block_index, interval_info)
        #
        # for block_index in sorted(self.constant_intervals):
        #     print(block_index, sorted(r for r in self.constant_intervals[block_index] if r.start != self.preamble_end), end=" ")
        #     print(" ".join([self.__get_hex_value_for_block(self.__blocks[block_index[0]], interval) for interval in sorted(r for r in self.constant_intervals[block_index] if r.start!=self.preamble_end)]))

    def __get_hex_value_for_block(self, block, interval):
        start, end = block.convert_range(interval.start + 1, interval.end, from_view=0, to_view=1, decoded=True)
        return block.decoded_hex_str[start:end]

    def find_constants(self):
        """
        Return a list of labels over constants in the protocol.
        A constant is the largest common interval, that appears in all constant intervals of all blocks.
        It suffices to search for the first block, because if the constant does not appear here, it cant be a constant.

        :rtype: list of ProtocolLabel
        """
        if not self.is_initialized:
            self.__find_constant_intervals()

        common_constant_intervals = set()

        for interval in self.constant_intervals[(0,1)]:
            candidate = interval
            for j in range(1, len(self.__blocks)):
                overlapping_intervals = {candidate.find_common_interval(other_interval) for other_interval in self.constant_intervals[(0, j)]}
                overlapping_intervals.discard(None)

                if len(overlapping_intervals) == 0:
                    candidate = None
                    break
                else:
                    candidate = max(overlapping_intervals)

            overlapping_candidate = next((c for c in common_constant_intervals if c.overlaps_with(candidate)), None)

            if overlapping_candidate is None:
                common_constant_intervals.add(candidate)
            else:
                common_constant_intervals.remove(overlapping_candidate)
                common_constant_intervals.add(max(candidate, overlapping_candidate))

        return [ProtocolLabel(start=interval.start, end=interval.end, name="Constant #{0}".format(i+1),
                              val_type_index=0, color_index=None) for i, interval in enumerate(common_constant_intervals)]

    def find_sync(self) -> ProtocolLabel:
        if self.preamble_end == 0:
            self.find_preamble()
        if not self.is_initialized:
            self.__find_constant_intervals()

        possible_sync_pos = defaultdict(int)
        for block_index, const_interval in self.constant_intervals.items():
            for const_range in const_interval:
                const_range = Interval(4 * ((const_range.start + 1) // 4) - 1, 4 * ((const_range.end + 1) // 4) - 1) # align to nibbles
                if const_range.start == self.preamble_end:
                   possible_sync_pos[const_range] += 1

        sync_interval = max(possible_sync_pos, key=possible_sync_pos.__getitem__)

        return ProtocolLabel(start=sync_interval.start + 1, end=sync_interval.end - 1,
                             name="Sync", color_index=None, val_type_index=0)


