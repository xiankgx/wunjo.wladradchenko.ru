import os
import cv2
import sys
import math
import torch
import subprocess
import numpy as np
from tqdm import tqdm
from time import strftime
from argparse import Namespace

root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
deepfake_root_path = os.path.join(root_path, "deepfake")
sys.path.insert(0, deepfake_root_path)

"""Video and image"""
from src.utils.videoio import (
    save_video_with_audio, cut_start_video, get_frames, get_first_frame, encrypted, save_frames,
    check_media_type, extract_audio_from_video, save_video_from_frames, video_to_frames
)
from src.utils.imageio import save_image_cv2, read_image_cv2, save_colored_mask_cv2
"""Video and image"""
"""Animation Face"""
from src.utils.preprocess import CropAndExtract
from src.test_audio2coeff import Audio2Coeff
from src.facerender.animate import AnimateFromCoeff
from src.generate_batch import get_data
from src.generate_facerender_batch import get_facerender_data
"""Animation Face"""
"""Wav2Lip"""
from src.wav2mel import MelProcessor
from src.utils.face_enhancer import enhancer as content_enhancer
from src.utils.video2fake import GenerateFakeVideo2Lip
"""Wav2Lip"""
"""Face Swap"""
from src.utils.faceswap import FaceSwapDeepfake
"""Face Swap"""
"""Retouch"""
from src.retouch import InpaintModel, process_retouch, pil_to_cv2, convert_cv2_to_pil, VideoRemoveObjectProcessor, convert_colored_mask_thickness_cv2, upscale_retouch_frame
"""Retouch"""
"""Segmentation"""
from src.utils.segment import SegmentAnything
"""Segmentation"""

sys.path.pop(0)

from cog import Input
import requests
import shutil
import json

from backend.folders import DEEPFAKE_MODEL_FOLDER, TMP_FOLDER
from backend.download import download_model, unzip, check_download_size, get_nested_url, is_connected


DEEPFAKE_JSON_URL = "https://wladradchenko.ru/static/wunjo.wladradchenko.ru/deepfake.json"


def get_config_deepfake() -> dict:
    try:
        response = requests.get(DEEPFAKE_JSON_URL)
        with open(os.path.join(DEEPFAKE_MODEL_FOLDER, 'deepfake.json'), 'wb') as file:
            file.write(response.content)
    except:
        print("Not internet connection to get actual versions of deepfake models")
    finally:
        if not os.path.isfile(os.path.join(DEEPFAKE_MODEL_FOLDER, 'deepfake.json')):
            deepfake = {}
        else:
            with open(os.path.join(DEEPFAKE_MODEL_FOLDER, 'deepfake.json'), 'r', encoding="utf8") as file:
                deepfake = json.load(file)

    return deepfake


file_deepfake_config = get_config_deepfake()


class AnimationFaceTalk:
    """
    Animation face talk on image or gif
    """
    @staticmethod
    def main_img_deepfake(source_image: str, driven_audio: str, deepfake_dir: str, still: bool = True, face_fields: list = None,
                          preprocess: str = Input(description="how to preprocess the images", choices=["crop", "resize", "full"], default="full",),
                          expression_scale=1.0, input_yaw=None, input_pitch=None, input_roll=None, pose_style=0, batch_size=2):

        if file_deepfake_config == {}:
            raise "[Error] Config file deepfake.json is not exist"
        # torch.backends.cudnn.enabled = False
        use_cpu = False if torch.cuda.is_available() and 'cpu' not in os.environ.get('WUNJO_TORCH_DEVICE', 'cpu') else True

        if torch.cuda.is_available() and not use_cpu:
            print("Processing will run on GPU")
            device = "cuda"
        else:
            print("Processing will run on CPU")
            device = "cpu"

        if preprocess is None:
            preprocess = "crop"

        save_dir = os.path.join(deepfake_dir, strftime("%Y_%m_%d_%H.%M.%S"))
        os.makedirs(save_dir, exist_ok=True)

        checkpoint_dir_full = os.path.join(DEEPFAKE_MODEL_FOLDER, "checkpoints")
        os.environ['TORCH_HOME'] = checkpoint_dir_full
        if not os.path.exists(checkpoint_dir_full):
            os.makedirs(checkpoint_dir_full)

        path_of_net_recon_model = os.path.join(checkpoint_dir_full, 'epoch_20.pth')
        link_of_net_recon_model = get_nested_url(file_deepfake_config, ["checkpoints", "epoch_20.pth"])
        if not os.path.exists(path_of_net_recon_model):
            # check what is internet access
            is_connected(path_of_net_recon_model)
            # download pre-trained models from url
            download_model(path_of_net_recon_model, link_of_net_recon_model)
        else:
            check_download_size(path_of_net_recon_model, link_of_net_recon_model)

        dir_of_BFM_fitting = os.path.join(checkpoint_dir_full, 'BFM_Fitting')
        link_of_BFM_fitting = get_nested_url(file_deepfake_config, ["checkpoints", "BFM_Fitting.zip"])
        if not os.path.exists(dir_of_BFM_fitting):
            # check what is internet access
            is_connected(dir_of_BFM_fitting)
            # download pre-trained models from url
            download_model(os.path.join(checkpoint_dir_full, 'BFM_Fitting.zip'), link_of_BFM_fitting)
            unzip(os.path.join(checkpoint_dir_full, 'BFM_Fitting.zip'), checkpoint_dir_full)
        else:
            check_download_size(os.path.join(checkpoint_dir_full, 'BFM_Fitting.zip'), link_of_BFM_fitting)
            if not os.listdir(dir_of_BFM_fitting):
                unzip(os.path.join(checkpoint_dir_full, 'BFM_Fitting.zip'), checkpoint_dir_full)

        dir_of_hub_models = os.path.join(checkpoint_dir_full, 'hub')
        link_of_hub_models = get_nested_url(file_deepfake_config, ["checkpoints", "hub.zip"])
        if not os.path.exists(dir_of_hub_models):
            # check what is internet access
            is_connected(dir_of_hub_models)
            # download pre-trained models from url
            download_model(os.path.join(checkpoint_dir_full, 'hub.zip'), link_of_hub_models)
            unzip(os.path.join(checkpoint_dir_full, 'hub.zip'), checkpoint_dir_full)
        else:
            check_download_size(os.path.join(checkpoint_dir_full, 'hub.zip'), link_of_hub_models)
            if not os.listdir(dir_of_hub_models):
                unzip(os.path.join(checkpoint_dir_full, 'hub.zip'), checkpoint_dir_full)

        wav2lip_checkpoint = os.path.join(checkpoint_dir_full, 'wav2lip.pth')
        link_wav2lip_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "wav2lip.pth"])
        if not os.path.exists(wav2lip_checkpoint):
            # check what is internet access
            is_connected(wav2lip_checkpoint)
            # download pre-trained models from url
            download_model(wav2lip_checkpoint, link_wav2lip_checkpoint)
        else:
            check_download_size(wav2lip_checkpoint, link_wav2lip_checkpoint)

        audio2pose_checkpoint = os.path.join(checkpoint_dir_full, 'auido2pose_00140-model.pth')
        link_audio2pose_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "auido2pose_00140-model.pth"])
        if not os.path.exists(audio2pose_checkpoint):
            # check what is internet access
            is_connected(audio2pose_checkpoint)
            # download pre-trained models from url
            download_model(audio2pose_checkpoint, link_audio2pose_checkpoint)
        else:
            check_download_size(audio2pose_checkpoint, link_audio2pose_checkpoint)
        audio2pose_yaml_path = os.path.join(deepfake_root_path, 'src', 'config', 'auido2pose.yaml')

        audio2exp_checkpoint = os.path.join(checkpoint_dir_full, 'auido2exp_00300-model.pth')
        link_audio2exp_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "auido2exp_00300-model.pth"])
        if not os.path.exists(audio2exp_checkpoint):
            # check what is internet access
            is_connected(audio2exp_checkpoint)
            # download pre-trained models from url
            download_model(audio2exp_checkpoint, link_audio2exp_checkpoint)
        else:
            check_download_size(audio2exp_checkpoint, link_audio2exp_checkpoint)
        audio2exp_yaml_path = os.path.join(deepfake_root_path, 'src', 'config', 'auido2exp.yaml')

        free_view_checkpoint = os.path.join(checkpoint_dir_full, 'facevid2vid_00189-model.pth.tar')
        link_free_view_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "facevid2vid_00189-model.pth.tar"])
        if not os.path.exists(free_view_checkpoint):
            # check what is internet access
            is_connected(free_view_checkpoint)
            # download pre-trained models from url
            download_model(free_view_checkpoint, link_free_view_checkpoint)
        else:
            check_download_size(free_view_checkpoint, link_free_view_checkpoint)

        if preprocess == 'full':
            mapping_checkpoint = os.path.join(checkpoint_dir_full, 'mapping_00109-model.pth.tar')
            link_mapping_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "mapping_00109-model.pth.tar"])
            if not os.path.exists(mapping_checkpoint):
                # check what is internet access
                is_connected(mapping_checkpoint)
                # download pre-trained models from url
                download_model(mapping_checkpoint, link_mapping_checkpoint)
            else:
                check_download_size(mapping_checkpoint, link_mapping_checkpoint)
            facerender_yaml_path = os.path.join(deepfake_root_path, 'src', 'config', 'facerender_still.yaml')
        else:
            mapping_checkpoint = os.path.join(checkpoint_dir_full, 'mapping_00229-model.pth.tar')
            link_mapping_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "mapping_00229-model.pth.tar"])
            if not os.path.exists(mapping_checkpoint):
                # check what is internet access
                is_connected(mapping_checkpoint)
                # download pre-trained models from url
                download_model(mapping_checkpoint, link_mapping_checkpoint)
            else:
                check_download_size(mapping_checkpoint, link_mapping_checkpoint)
            facerender_yaml_path = os.path.join(deepfake_root_path, 'src', 'config', 'facerender.yaml')

        # init model
        print("Starting to crop and extract frames")
        preprocess_model = CropAndExtract(DEEPFAKE_MODEL_FOLDER, path_of_net_recon_model, dir_of_BFM_fitting, device, face_fields)

        print("Starting get audio coefficient")
        audio_to_coeff = Audio2Coeff(audio2pose_checkpoint, audio2pose_yaml_path, audio2exp_checkpoint, audio2exp_yaml_path, wav2lip_checkpoint, device)

        print("Starting animate face from audio coefficient")
        animate_from_coeff = AnimateFromCoeff(free_view_checkpoint, mapping_checkpoint, facerender_yaml_path, device)

        # crop image and extract 3dmm from image
        first_frame_dir = os.path.join(save_dir, 'first_frame_dir')
        os.makedirs(first_frame_dir, exist_ok=True)

        print('Extraction 3DMM for source image')
        pic_path_type = check_media_type(source_image)
        first_coeff_path, crop_pic_path, crop_info = preprocess_model.generate(source_image, first_frame_dir, preprocess, source_image_flag=True, pic_path_type=pic_path_type)
        if first_coeff_path is None:
            print("Can't get the coefficients by 3DMM of the input")
            return

        ref_eyeblink_coeff_path = None
        ref_pose_coeff_path = None

        # audio2ceoff
        batch = get_data(first_coeff_path, driven_audio, device, ref_eyeblink_coeff_path, still=still)
        coeff_path = audio_to_coeff.generate(batch, save_dir, pose_style, ref_pose_coeff_path)

        # coeff2video
        data = get_facerender_data(coeff_path, crop_pic_path, first_coeff_path, driven_audio, batch_size, input_yaw, input_pitch, input_roll, expression_scale=expression_scale, still_mode=still, preprocess=preprocess)
        mp4_path = animate_from_coeff.generate(data, save_dir, source_image, crop_info, preprocess=preprocess, pic_path_type=pic_path_type, device=device)

        for f in os.listdir(save_dir):
            if mp4_path == f:
                mp4_path = os.path.join(save_dir, f)
            else:
                if os.path.isfile(os.path.join(save_dir, f)):
                    os.remove(os.path.join(save_dir, f))
                elif os.path.isdir(os.path.join(save_dir, f)):
                    shutil.rmtree(os.path.join(save_dir, f))

        return mp4_path


class AnimationMouthTalk:
    """
    Animation mouth talk on video
    """
    @staticmethod
    def main_video_deepfake(deepfake_dir: str, face: str, audio: str, static: bool = False, face_fields: list = None,
                            box: list = [-1, -1, -1, -1], video_start: float = 0,
                            video_end: float = 0, emotion_label: int = None, similar_coeff: float = 0.96):
        args = AnimationMouthTalk.load_video_default()
        use_cpu = False if torch.cuda.is_available() and 'cpu' not in os.environ.get('WUNJO_TORCH_DEVICE', 'cpu') else True

        if torch.cuda.is_available() and not use_cpu:
            print("Processing will run on GPU")
            device = "cuda"
        else:
            print("Processing will run on CPU")
            device = "cpu"

        save_dir = os.path.join(deepfake_dir, strftime("%Y_%m_%d_%H.%M.%S"))
        os.makedirs(save_dir, exist_ok=True)

        checkpoint_dir_full = os.path.join(DEEPFAKE_MODEL_FOLDER, "checkpoints")
        os.environ['TORCH_HOME'] = checkpoint_dir_full
        if not os.path.exists(checkpoint_dir_full):
            os.makedirs(checkpoint_dir_full)

        if emotion_label is None:
            wav2lip_checkpoint = os.path.join(checkpoint_dir_full, 'wav2lip.pth')
            link_wav2lip_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "wav2lip.pth"])
            if not os.path.exists(wav2lip_checkpoint):
                # check what is internet access
                is_connected(wav2lip_checkpoint)
                # download pre-trained models from url
                download_model(wav2lip_checkpoint, link_wav2lip_checkpoint)
            else:
                check_download_size(wav2lip_checkpoint, link_wav2lip_checkpoint)
        else:
            wav2lip_checkpoint = os.path.join(checkpoint_dir_full, 'emo2lip.pth')
            link_wav2lip_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "emo2lip.pth"])
            if not os.path.exists(wav2lip_checkpoint):
                # check what is internet access
                is_connected(wav2lip_checkpoint)
                # download pre-trained models from url
                download_model(wav2lip_checkpoint, link_wav2lip_checkpoint)
            else:
                check_download_size(wav2lip_checkpoint, link_wav2lip_checkpoint)

        # If video_start is not 0 when cut video from start
        face = cut_start_video(face, float(video_start), float(video_end))

        # get video frames
        # TODO if users will have problem with RAM for this method, when change approach on save frames in files
        frames, fps = get_frames(video=face, rotate=args.rotate, crop=args.crop, resize_factor=args.resize_factor)
        # get mel of audio
        mel_processor = MelProcessor(audio=audio, save_output=save_dir, fps=fps)
        mel_chunks = mel_processor.process()
        # create wav to lip
        full_frames = frames[:len(mel_chunks)]
        batch_size = args.wav2lip_batch_size
        wav2lip = GenerateFakeVideo2Lip(DEEPFAKE_MODEL_FOLDER, emotion_label=emotion_label, similar_coeff=similar_coeff)
        wav2lip.face_fields = face_fields

        print("Face detect starting")
        gen = wav2lip.datagen(
            full_frames.copy(), mel_chunks, box, static, args.img_size, args.wav2lip_batch_size,
            args.pads, args.nosmooth
        )
        # load wav2lip
        print("Starting mouth animate")
        wav2lip_processed_video = wav2lip.generate_video_from_chunks(gen, mel_chunks, batch_size, wav2lip_checkpoint, device, save_dir, fps)
        if wav2lip_processed_video is None:
            return
        wav2lip_result_video = wav2lip_processed_video
        mp4_path = save_video_with_audio(wav2lip_result_video, audio, save_dir)

        for f in os.listdir(save_dir):
            if mp4_path == f:
                mp4_path = os.path.join(save_dir, f)
            else:
                if os.path.isfile(os.path.join(save_dir, f)):
                    os.remove(os.path.join(save_dir, f))
                elif os.path.isdir(os.path.join(save_dir, f)):
                    shutil.rmtree(os.path.join(save_dir, f))

        for f in os.listdir(TMP_FOLDER):
            os.remove(os.path.join(TMP_FOLDER, f))

        return mp4_path

    @staticmethod
    def load_video_default():
        return Namespace(
            pads=[0, 10, 0, 0],
            face_det_batch_size=16,
            wav2lip_batch_size=128,
            resize_factor=1,
            crop=[0, -1, 0, -1],
            rotate=False,
            nosmooth=False,
            img_size=96
        )



class FaceSwap:
    """
    Face swap by one photo
    """
    @staticmethod
    def main_faceswap(deepfake_dir: str, target: str, target_face_fields: str, source: str, source_face_fields: str,
                      type_file_source: str, target_video_start: float = 0, target_video_end: float = 0,
                      source_current_time: float = 0, source_video_end: float = 0,
                      multiface: bool = False, similarface: bool = False, similar_coeff: float = 0.95):
        args = FaceSwap.load_faceswap_default()

        use_cpu = False if torch.cuda.is_available() and 'cpu' not in os.environ.get('WUNJO_TORCH_DEVICE', 'cpu') else True

        if torch.cuda.is_available() and not use_cpu:
            print("Processing will run on GPU")
            device = "cuda"
        else:
            print("Processing will run on CPU")
            device = "cpu"

        save_dir = os.path.join(deepfake_dir, strftime("%Y_%m_%d_%H.%M.%S"))
        os.makedirs(save_dir, exist_ok=True)

        model_user_path = DEEPFAKE_MODEL_FOLDER

        checkpoint_dir_full = os.path.join(model_user_path, "checkpoints")
        os.environ['TORCH_HOME'] = checkpoint_dir_full
        if not os.path.exists(checkpoint_dir_full):
            os.makedirs(checkpoint_dir_full)

        faceswap_checkpoint = os.path.join(checkpoint_dir_full, 'faceswap.onnx')
        link_faceswap_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "faceswap.onnx"])
        if not os.path.exists(faceswap_checkpoint):
            # check what is internet access
            is_connected(faceswap_checkpoint)
            # download pre-trained models from url
            download_model(faceswap_checkpoint, link_faceswap_checkpoint)
        else:
            check_download_size(faceswap_checkpoint, link_faceswap_checkpoint)

        faceswap = FaceSwapDeepfake(DEEPFAKE_MODEL_FOLDER, faceswap_checkpoint, similarface, similar_coeff, device)

        # transfer video without format from frontend to mp4 format
        if type_file_source == "video":
            source = cut_start_video(source, 0, float(source_video_end))
        # get fps and calculate current frame and get that frame for source
        source_frame = get_first_frame(source, float(source_current_time))
        source_face = faceswap.face_detect_with_alignment_from_source_frame(source_frame, source_face_fields)

        # if this is video target
        type_file_target = check_media_type(target)
        if type_file_target == "animated":
            # If video_start for target is not 0 when cut video from start
            target = cut_start_video(target, float(target_video_start), float(target_video_end))

            # get video frame for source if type is video
            frame_dir = os.path.join(save_dir, "frames")
            os.makedirs(frame_dir, exist_ok=True)

            fps, frame_dir = save_frames(video=target, output_dir=frame_dir, rotate=args.rotate, crop=args.crop, resize_factor=args.resize_factor)
            # create face swap
            file_name = faceswap.swap_video(frame_dir, source_face, target_face_fields, save_dir, multiface, fps)
            saved_file = os.path.join(save_dir, file_name)
            # after generation
            try:
                file_name = encrypted(saved_file, save_dir)  # encrypted
                saved_file = os.path.join(save_dir, file_name)
            except Exception as err:
                print(f"Error with encrypted {err}")

            # get audio from video target
            audio_file_name = extract_audio_from_video(target, save_dir)
            # combine audio and video
            file_name = save_video_with_audio(saved_file, os.path.join(save_dir, str(audio_file_name)), save_dir)

        else:  # static file
            # create face swap on image
            target_frame = get_first_frame(target)
            target_image = faceswap.swap_image(target_frame, source_face, target_face_fields, save_dir, multiface)
            file_name = "swap_result.png"
            saved_file = save_image_cv2(os.path.join(save_dir, file_name), target_image)
            # after generation
            try:
                file_name = encrypted(saved_file, save_dir)  # encrypted
            except Exception as err:
                print(f"Error with encrypted {err}")

        for f in os.listdir(save_dir):
            if file_name == f:
                file_name = os.path.join(save_dir, f)
            else:
                if os.path.isfile(os.path.join(save_dir, f)):
                    os.remove(os.path.join(save_dir, f))
                elif os.path.isdir(os.path.join(save_dir, f)):
                    shutil.rmtree(os.path.join(save_dir, f))

        for f in os.listdir(TMP_FOLDER):
            os.remove(os.path.join(TMP_FOLDER, f))

        return file_name

    @staticmethod
    def load_faceswap_default():
        return Namespace(
            resize_factor=1,
            crop=[0, -1, 0, -1],
            rotate=False,
        )


class Retouch:
    """Retouch image or video"""

    @staticmethod
    def main_retouch(output: str, source: str, masks: dict, retouch_model_type: str = "retouch_object", predictor=None,
                     session=None, source_start: float = 0, source_end: float = 0, source_type: str = "img",
                     mask_color: str = None, upscale: bool = True, blur: int = 1, segment_percentage: int = 25):
        # create folder
        save_dir = os.path.join(output, strftime("%Y_%m_%d_%H.%M.%S"))
        os.makedirs(save_dir, exist_ok=True)
        # create tmp folder
        tmp_dir = os.path.join(save_dir, "tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        # frame folder
        frame_dir = os.path.join(tmp_dir, "frame")
        os.makedirs(frame_dir, exist_ok=True)
        # resized frame folder
        resized_dir = os.path.join(tmp_dir, "resized")
        os.makedirs(resized_dir, exist_ok=True)
        # get device
        use_cpu = False if torch.cuda.is_available() and 'cpu' not in os.environ.get('WUNJO_TORCH_DEVICE', 'cpu') else True
        if torch.cuda.is_available() and not use_cpu:
            print("Processing will run on GPU")
            device = "cuda"
            use_half = True
        else:
            print("Processing will run on CPU")
            device = "cpu"
            use_half = False
        # get models path
        checkpoint_folder = os.path.join(DEEPFAKE_MODEL_FOLDER, "checkpoints")
        os.environ['TORCH_HOME'] = checkpoint_folder
        if not os.path.exists(checkpoint_folder):
            os.makedirs(checkpoint_folder)

        # load model improved remove object
        model_pro_painter_path = os.path.join(checkpoint_folder, "ProPainter.pth")
        link_pro_painter = get_nested_url(file_deepfake_config, ["checkpoints", "ProPainter.pth"])
        if not os.path.exists(model_pro_painter_path):
            # check what is internet access
            is_connected(model_pro_painter_path)
            # download pre-trained models from url
            download_model(model_pro_painter_path, link_pro_painter)
        else:
            check_download_size(model_pro_painter_path, link_pro_painter)

        model_raft_things_path = os.path.join(checkpoint_folder, "raft-things.pth")
        link_raft_things = get_nested_url(file_deepfake_config, ["checkpoints", "raft-things.pth"])
        if not os.path.exists(model_raft_things_path):
            # check what is internet access
            is_connected(model_raft_things_path)
            # download pre-trained models from url
            download_model(model_raft_things_path, link_raft_things)
        else:
            check_download_size(model_raft_things_path, link_raft_things)

        model_recurrent_flow_path = os.path.join(checkpoint_folder, "recurrent_flow_completion.pth")
        link_recurrent_flow = get_nested_url(file_deepfake_config, ["checkpoints", "recurrent_flow_completion.pth"])
        if not os.path.exists(model_recurrent_flow_path):
            # check what is internet access
            is_connected(model_recurrent_flow_path)
            # download pre-trained models from url
            download_model(model_recurrent_flow_path, link_recurrent_flow)
        else:
            check_download_size(model_recurrent_flow_path, link_recurrent_flow)

        # load model retouch
        if retouch_model_type == "retouch_face":
            retouch_model_name = "retouch_face"
            model_retouch_path = os.path.join(checkpoint_folder, "retouch_face.pth")
        else:
            retouch_model_name = "retouch_object"
            model_retouch_path = os.path.join(checkpoint_folder, "retouch_object.pth")

        link_model_retouch = get_nested_url(file_deepfake_config, ["checkpoints", f"{retouch_model_name}.pth"])
        if not os.path.exists(model_retouch_path):
            # check what is internet access
            is_connected(model_retouch_path)
            # download pre-trained models from url
            download_model(model_retouch_path, link_model_retouch)
        else:
            check_download_size(model_retouch_path, link_model_retouch)

        # load model segmentation
        if device == "cuda":
            vit_model_type = "vit_h"

            sam_vit_checkpoint = os.path.join(checkpoint_folder, 'sam_vit_h.pth')
            link_sam_vit_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "sam_vit_h.pth"])
            if not os.path.exists(sam_vit_checkpoint):
                # check what is internet access
                is_connected(sam_vit_checkpoint)
                # download pre-trained models from url
                download_model(sam_vit_checkpoint, link_sam_vit_checkpoint)
            else:
                check_download_size(sam_vit_checkpoint, link_sam_vit_checkpoint)

            onnx_vit_checkpoint = os.path.join(checkpoint_folder, 'vit_h_quantized.onnx')
            link_onnx_vit_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "vit_h_quantized.onnx"])
            if not os.path.exists(onnx_vit_checkpoint):
                # check what is internet access
                is_connected(onnx_vit_checkpoint)
                # download pre-trained models from url
                download_model(onnx_vit_checkpoint, link_onnx_vit_checkpoint)
            else:
                check_download_size(onnx_vit_checkpoint, link_onnx_vit_checkpoint)
        else:
            vit_model_type = "vit_b"

            sam_vit_checkpoint = os.path.join(checkpoint_folder, 'sam_vit_b.pth')
            link_sam_vit_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "sam_vit_b.pth"])
            if not os.path.exists(sam_vit_checkpoint):
                # check what is internet access
                is_connected(sam_vit_checkpoint)
                # download pre-trained models from url
                download_model(sam_vit_checkpoint, link_sam_vit_checkpoint)
            else:
                check_download_size(sam_vit_checkpoint, link_sam_vit_checkpoint)

            onnx_vit_checkpoint = os.path.join(checkpoint_folder, 'vit_b_quantized.onnx')
            link_onnx_vit_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "vit_b_quantized.onnx"])
            if not os.path.exists(onnx_vit_checkpoint):
                # check what is internet access
                is_connected(onnx_vit_checkpoint)
                # download pre-trained models from url
                download_model(onnx_vit_checkpoint, link_onnx_vit_checkpoint)
            else:
                check_download_size(onnx_vit_checkpoint, link_onnx_vit_checkpoint)

        # segment
        segment_percentage = segment_percentage / 100
        segmentation = SegmentAnything(segment_percentage)
        if session is None:
            session = segmentation.init_onnx(onnx_vit_checkpoint, device)
        if predictor is None:
            predictor = segmentation.init_vit(sam_vit_checkpoint, vit_model_type, device)

        # cut video
        if source_type == "video":
            source = cut_start_video(source, source_start, source_end)

        remove_keys = []
        for key in masks.keys():
            if masks[key].get("start_time") < source_start:
                remove_keys += [key]
                continue
            if masks[key].get("start_time") > source_end:
                remove_keys += [key]
                continue
            if masks[key].get("end_time") > source_end:
                # if video was cut in end
                masks[key]["end_time"] = source_end
            # if start cud need to reduce end time
            masks[key]["end_time"] = masks[key]["end_time"] - source_start
            # if video was cut in start
            masks[key]["start_time"] = masks[key]["start_time"] - source_start
        else:
            for remove_key in remove_keys:
                masks.pop(remove_key)

        source_media_type = check_media_type(source)
        if source_media_type == "static":
            fps = 0
            # Save frame to frame_dir
            frame_files = ["static_frame.png"]
            cv2.imwrite(os.path.join(frame_dir, frame_files[0]), read_image_cv2(source))
        elif source_media_type == "animated":
            fps, frame_dir = save_frames(video=source, output_dir=frame_dir, rotate=False, crop=[0, -1, 0, -1], resize_factor=1)
            frame_files = sorted(os.listdir(frame_dir))
        else:
            raise "Source is not detected as image or video"

        first_frame = read_image_cv2(os.path.join(frame_dir, frame_files[0]))
        orig_height, orig_width, _ = first_frame.shape
        frame_batch_size = 50  # for improve remove object to limit VRAM, for CPU slowly, but people have a lot RAM
        work_dir = frame_dir

        if source_media_type == "animated" and retouch_model_type == "improved_retouch_object" and device == "cuda":
            # resize only for VRAM
            gpu_vram = torch.cuda.get_device_properties(device).total_memory / (1024 ** 3)
            # table of gpu memory
            gpu_table = {19: 1280, 7: 720, 6: 640, 2: 320}
            # get user resize for gpu
            max_size = max(val for key, val in gpu_table.items() if key <= gpu_vram)
            print(f"Limit VRAM is {gpu_vram} Gb. Video will resize before {max_size} for max size")
            # Resize frames while maintaining aspect ratio
            for frame_file in frame_files:
                frame = read_image_cv2(os.path.join(frame_dir, frame_file))
                h, w, _ = frame.shape
                if max(h, w) > max_size:
                    if h > w:
                        new_h = max_size
                        new_w = int(w * (max_size / h))
                    else:
                        new_w = max_size
                        new_h = int(h * (max_size / w))
                    resized_frame = cv2.resize(frame, (new_w, new_h))
                    cv2.imwrite(os.path.join(resized_dir, frame_file), resized_frame)
                else:
                    cv2.imwrite(os.path.join(resized_dir, frame_file), frame)
            work_dir = resized_dir

        # read again after resized
        first_work_frame = read_image_cv2(os.path.join(work_dir, frame_files[0]))
        work_height, work_width, _ = first_work_frame.shape

        # get segmentation frames as maks
        segmentation.load_models(predictor=predictor, session=session)
        thickness_mask = 10

        for key in masks.keys():
            print(f"Processing ID: {key}")
            mask_key_save_path = os.path.join(tmp_dir, f"mask_{key}")
            os.makedirs(mask_key_save_path, exist_ok=True)
            start_time = masks[key]["start_time"]
            end_time = masks[key]["end_time"]
            start_frame = math.floor(start_time * fps)
            end_frame = math.ceil(end_time * fps) + 1
            # list of frames of list of one frame
            filter_frames_files = frame_files[start_frame:end_frame]
            # set progress bar
            progress_bar = tqdm(total=len(filter_frames_files), unit='it', unit_scale=True)
            filter_frame_file_name = filter_frames_files[0]
            # read mot resized files
            # TODO [1] work_dir has resized frames, but in this case I don't know quality of image after resize influence on segmentation quality? if not when use work_dir better else need to use frame_dir and resized on retouch
            filter_frame = cv2.imread(os.path.join(work_dir, filter_frame_file_name))  # read first frame file after filter
            # get segment mask
            segment_mask = segmentation.set_obj(point_list=masks[key]["point_list"], frame=filter_frame)
            # save first frame as 0001
            segmentation.save_black_mask(filter_frame_file_name, segment_mask, mask_key_save_path, kernel_size=thickness_mask, width=work_width, height=work_height)
            if mask_color:
                color = segmentation.hex_to_rgba(mask_color)
                os.makedirs(os.path.join(save_dir, key), exist_ok=True)
                orig_filter_frame = cv2.imread(os.path.join(frame_dir, filter_frame_file_name))
                saving_mask = segmentation.apply_mask_on_frame(segment_mask, orig_filter_frame, color, orig_width, orig_height)
                saving_mask.save(os.path.join(save_dir, key, filter_frame_file_name))

            # update progress bar
            progress_bar.update(1)

            if len(filter_frames_files) > 1:
                for filter_frame_file_name in filter_frames_files[1:]:
                    # TODO [1] work_dir has resized frames, but in this case I don't know quality of image after resize influence on segmentation quality? if not when use work_dir better else need to use frame_dir and resized on retouch
                    filter_frame = cv2.imread(os.path.join(work_dir, filter_frame_file_name))  # read frame file after filter
                    segment_mask = segmentation.draw_mask_frames(frame=filter_frame)
                    if segment_mask is None:
                        print(key, "Encountered None mask. Breaking the loop.")
                        break
                    # save frames after 0002
                    segmentation.save_black_mask(filter_frame_file_name, segment_mask, mask_key_save_path, kernel_size=thickness_mask, width=work_width, height=work_height)
                    if mask_color:
                        color = segmentation.hex_to_rgba(mask_color)
                        orig_filter_frame = cv2.imread(os.path.join(frame_dir, filter_frame_file_name))
                        saving_mask = segmentation.apply_mask_on_frame(segment_mask, orig_filter_frame, color, orig_width, orig_height)
                        saving_mask.save(os.path.join(save_dir, key, filter_frame_file_name))

                    progress_bar.update(1)
            # set new key
            masks[key]["frame_files_path"] = mask_key_save_path
            # close progress bar for key
            progress_bar.close()

        if mask_color:
            print("Mask save is finished. Open folder")
            if os.path.exists(save_dir):
                if sys.platform == 'win32':
                    # Open folder for Windows
                    subprocess.Popen(r'explorer /select,"{}"'.format(save_dir))
                elif sys.platform == 'darwin':
                    # Open folder for MacOS
                    subprocess.Popen(['open', save_dir])
                elif sys.platform == 'linux':
                    # Open folder for Linux
                    subprocess.Popen(['xdg-open', save_dir])

        del segmentation, predictor, session
        torch.cuda.empty_cache()

        if retouch_model_type is None:
            for f in os.listdir(TMP_FOLDER):
                os.remove(os.path.join(TMP_FOLDER, f))
            # remove tmp dir
            shutil.rmtree(tmp_dir)
            return save_dir

        if source_media_type == "animated" and retouch_model_type == "improved_retouch_object":
            # raft
            retouch_processor = VideoRemoveObjectProcessor(device, model_raft_things_path, model_recurrent_flow_path, model_pro_painter_path)
            overlap = int(0.2 * frame_batch_size)

            for key in masks.keys():
                mask_files = sorted(os.listdir(masks[key]["frame_files_path"]))

                # processing video with batch size because of limit VRAM
                if len(mask_files) < 3:
                    continue

                for i in range(0, len(mask_files), frame_batch_size - overlap):
                    if len(mask_files) - i < 3:  # not less than 3 frames for batch
                        continue
                    # read mask by batch_size and convert back from file image
                    current_mask_files = mask_files[i: i + frame_batch_size]
                    inpaint_mask_frames = [cv2.imread(os.path.join(tmp_dir, f"mask_{key}", current_mask_file), cv2.IMREAD_GRAYSCALE) for current_mask_file in current_mask_files]
                    # Binarize the image
                    binary_masks = []
                    for idx, inpaint_mask_frame in enumerate(inpaint_mask_frames):
                        binary_mask = cv2.threshold(inpaint_mask_frame, 128, 1, cv2.THRESH_BINARY)[1]
                        # If it's not the first batch and the frame is within the overlap range, set the mask to false
                        if i > 0 and idx < overlap:
                            binary_mask = np.zeros_like(binary_mask)
                        bool_mask = binary_mask.astype(bool)
                        reshaped_mask = bool_mask[np.newaxis, np.newaxis, ...]
                        binary_masks.append(reshaped_mask)
                    # read frames by name of current_mask_files
                    current_frame_files = current_mask_files
                    current_frames = [cv2.imread(os.path.join(work_dir, current_frame_file)) for current_frame_file in current_frame_files]

                    # convert frame to pillow
                    current_frames = [retouch_processor.transfer_to_pil(f) for f in current_frames]
                    resized_frames, size, out_size = retouch_processor.resize_frames(current_frames)
                    width, height = size

                    flow_masks, masks_dilated = retouch_processor.read_retouch_mask(binary_masks, width, height, kernel_size=blur)
                    update_frames, flow_masks, masks_dilated, masked_frame_for_save, frames_inp = retouch_processor.process_frames_with_retouch_mask(frames=resized_frames, masks_dilated=masks_dilated, flow_masks=flow_masks, height=height, width=width)
                    comp_frames = retouch_processor.process_video_with_mask(update_frames, masks_dilated, flow_masks, frames_inp, width, height, use_half=use_half)
                    comp_frames = [cv2.resize(f, out_size) for f in comp_frames]
                    comp_frames_bgr = [cv2.cvtColor(f, cv2.COLOR_RGB2BGR) for f in comp_frames]
                    # update frames in work dir
                    for j in range(len(comp_frames_bgr)):
                        cv2.imwrite(os.path.join(work_dir, current_frame_files[j]), comp_frames_bgr[j])
                        # upscale frame
                        if upscale:
                            orig_frame = cv2.imread(os.path.join(frame_dir, current_frame_files[j]))
                            retouched_orig_frame = upscale_retouch_frame(mask=binary_masks[j], frame=comp_frames_bgr[j],  original_frame=orig_frame, width=orig_width, height=orig_height)
                            cv2.imwrite(os.path.join(frame_dir, current_frame_files[j]), retouched_orig_frame)
            # empty cache
            del retouch_processor
            torch.cuda.empty_cache()
        else:
            # retouch
            model_retouch = InpaintModel(model_path=model_retouch_path)

            for key in masks.keys():
                mask_files = sorted(os.listdir(masks[key]["frame_files_path"]))
                # set progress bar
                progress_bar = tqdm(total=len(mask_files), unit='it', unit_scale=True)
                for file_name in mask_files:
                    # read mask to pillow
                    segment_mask = cv2.imread(os.path.join(tmp_dir, f"mask_{key}", file_name), cv2.IMREAD_GRAYSCALE)
                    binary_mask = cv2.threshold(segment_mask, 128, 1, cv2.THRESH_BINARY)[1]
                    bool_mask = binary_mask.astype(bool)
                    reshaped_mask = bool_mask[np.newaxis, np.newaxis, ...]
                    segment_mask_pil = convert_colored_mask_thickness_cv2(reshaped_mask)
                    # read frame to pillow
                    current_frame = cv2.imread(os.path.join(work_dir, file_name))
                    frame_pil = convert_cv2_to_pil(current_frame)
                    # retouch_frame
                    retouch_frame = process_retouch(img=frame_pil, mask=segment_mask_pil, model=model_retouch)
                    # update frame
                    cv2.imwrite(os.path.join(work_dir, file_name), pil_to_cv2(retouch_frame))
                    progress_bar.update(1)
                # close progress bar for key
                progress_bar.close()
            # empty cache
            del model_retouch
            torch.cuda.empty_cache()

        if upscale:
            # if upscale and was improved animation when change resized dir back
            # for other methods this will not influence
            work_dir = frame_dir

        if source_media_type == "animated":
            # get saved file as merge frames to video
            video_name = save_video_from_frames(frame_names="frame%04d.png", save_path=work_dir, fps=fps, alternative_save_path=save_dir)
            # get audio from video target
            audio_file_name = extract_audio_from_video(source, save_dir)
            # combine audio and video
            save_name = save_video_with_audio(os.path.join(save_dir, video_name), os.path.join(save_dir, str(audio_file_name)), save_dir)
        else:
            save_name = frame_files[0]
            retouched_frame = read_image_cv2(os.path.join(work_dir, save_name))
            cv2.imwrite(os.path.join(save_dir, save_name), retouched_frame)

        # remove tmp dir
        shutil.rmtree(tmp_dir)

        for f in os.listdir(TMP_FOLDER):
            os.remove(os.path.join(TMP_FOLDER, f))

        return os.path.join(save_dir, save_name)


class VideoEdit:
    """Edit video"""
    @staticmethod
    def main_video_work(output, source, is_get_frames, enhancer="gfpgan", media_start=0, media_end=0):
        save_dir = os.path.join(output, strftime("%Y_%m_%d_%H.%M.%S"))
        os.makedirs(save_dir, exist_ok=True)

        media_start = float(media_start)
        media_end = float(media_end)

        import time
        time.sleep(5)

        audio_file_name = extract_audio_from_video(source, save_dir)

        if enhancer:
            use_cpu = False if torch.cuda.is_available() and 'cpu' not in os.environ.get('WUNJO_TORCH_DEVICE', 'cpu') else True
            if torch.cuda.is_available() and not use_cpu:
                print("Processing will run on GPU")
                device = "cuda"
            else:
                print("Processing will run on CPU")
                device = "cpu"

            print("Get audio and video frames")
            _, fps = get_frames(video=source, rotate=False, crop=[0, -1, 0, -1], resize_factor=1)
            if check_media_type(source) == "animated":
                source = cut_start_video(source, media_start, media_end)
                print("Starting improve video")
                enhanced_name = content_enhancer(source, save_folder=save_dir, method=enhancer, fps=float(fps), device=device)
                enhanced_path = os.path.join(save_dir, enhanced_name)
                save_name = save_video_with_audio(enhanced_path, os.path.join(save_dir, audio_file_name), save_dir)
            else:
                print("Starting improve image")
                save_name = content_enhancer(source, save_folder=save_dir, method=enhancer, device=device)

            for f in os.listdir(save_dir):
                if save_name == f:
                    save_name = os.path.join(save_dir, f)
                else:
                    if os.path.isfile(os.path.join(save_dir, f)):
                        os.remove(os.path.join(save_dir, f))
                    elif os.path.isdir(os.path.join(save_dir, f)):
                        shutil.rmtree(os.path.join(save_dir, f))

            for f in os.listdir(TMP_FOLDER):
                os.remove(os.path.join(TMP_FOLDER, f))

            return save_name

        if is_get_frames:
            source = cut_start_video(source, media_start, media_end)
            video_to_frames(source, save_dir)
            for f in os.listdir(TMP_FOLDER):
                os.remove(os.path.join(TMP_FOLDER, f))

            if os.path.exists(save_dir):
                if sys.platform == 'win32':
                    # Open folder for Windows
                    subprocess.Popen(r'explorer /select,"{}"'.format(save_dir))
                elif sys.platform == 'darwin':
                    # Open folder for MacOS
                    subprocess.Popen(['open', save_dir])
                elif sys.platform == 'linux':
                    # Open folder for Linux
                    subprocess.Popen(['xdg-open', save_dir])

            print(f"You will find images in {save_dir}")
            return os.path.join(save_dir, audio_file_name)

        print("Error... Not get parameters for video edit!")
        return "Error"

    @staticmethod
    def main_merge_frames(output, source_folder, audio_path, fps):
        save_dir = os.path.join(output, strftime("%Y_%m_%d_%H.%M.%S"))
        os.makedirs(save_dir, exist_ok=True)

        # get saved file as merge frames to video
        video_name = save_video_from_frames(frame_names="%d.png", save_path=source_folder, fps=fps)

        # combine audio and video
        video_name = save_video_with_audio(os.path.join(source_folder, video_name), str(audio_path), save_dir)

        for f in os.listdir(TMP_FOLDER):
            os.remove(os.path.join(TMP_FOLDER, f))

        return os.path.join(save_dir, video_name)


class GetSegment:
    @staticmethod
    def load_model():
        use_cpu = False if torch.cuda.is_available() and 'cpu' not in os.environ.get('WUNJO_TORCH_DEVICE', 'cpu') else True

        if torch.cuda.is_available() and not use_cpu:
            print("Processing will run on GPU")
            device = "cuda"
        else:
            print("Processing will run on CPU")
            device = "cpu"

        checkpoint_dir = "checkpoints"
        checkpoint_dir_full = os.path.join(DEEPFAKE_MODEL_FOLDER, checkpoint_dir)
        os.environ['TORCH_HOME'] = checkpoint_dir_full

        if device == "cuda":
            model_type = "vit_h"

            sam_vit_checkpoint = os.path.join(checkpoint_dir_full, 'sam_vit_h.pth')
            link_sam_vit_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "sam_vit_h.pth"])
            if not os.path.exists(sam_vit_checkpoint):
                # check what is internet access
                is_connected(sam_vit_checkpoint)
                # download pre-trained models from url
                download_model(sam_vit_checkpoint, link_sam_vit_checkpoint)
            else:
                check_download_size(sam_vit_checkpoint, link_sam_vit_checkpoint)

            onnx_vit_checkpoint = os.path.join(checkpoint_dir_full, 'vit_h_quantized.onnx')
            link_onnx_vit_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "vit_h_quantized.onnx"])
            if not os.path.exists(onnx_vit_checkpoint):
                # check what is internet access
                is_connected(onnx_vit_checkpoint)
                # download pre-trained models from url
                download_model(onnx_vit_checkpoint, link_onnx_vit_checkpoint)
            else:
                check_download_size(onnx_vit_checkpoint, link_onnx_vit_checkpoint)
        else:
            model_type = "vit_b"

            sam_vit_checkpoint = os.path.join(checkpoint_dir_full, 'sam_vit_b.pth')
            link_sam_vit_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "sam_vit_b.pth"])
            if not os.path.exists(sam_vit_checkpoint):
                # check what is internet access
                is_connected(sam_vit_checkpoint)
                # download pre-trained models from url
                download_model(sam_vit_checkpoint, link_sam_vit_checkpoint)
            else:
                check_download_size(sam_vit_checkpoint, link_sam_vit_checkpoint)

            onnx_vit_checkpoint = os.path.join(checkpoint_dir_full, 'vit_b_quantized.onnx')
            link_onnx_vit_checkpoint = get_nested_url(file_deepfake_config, ["checkpoints", "vit_b_quantized.onnx"])
            if not os.path.exists(onnx_vit_checkpoint):
                # check what is internet access
                is_connected(onnx_vit_checkpoint)
                # download pre-trained models from url
                download_model(onnx_vit_checkpoint, link_onnx_vit_checkpoint)
            else:
                check_download_size(onnx_vit_checkpoint, link_onnx_vit_checkpoint)

        segmentation = SegmentAnything()
        predictor = segmentation.init_vit(sam_vit_checkpoint, model_type, device)
        session = segmentation.init_onnx(onnx_vit_checkpoint, device)

        return {"predictor": predictor, "session": session}

    @staticmethod
    def get_segment_mask_file(predictor, session, source: str, point_list: list):
        # set time sleep else file will not still loaded
        import time
        time.sleep(5)
        # read frame
        source_media_type = check_media_type(source)
        if source_media_type == "static":
            frame = read_image_cv2(source)
        elif source_media_type == "animated":
            frames, _ = get_frames(video=source, rotate=False, crop=[0, -1, 0, -1], resize_factor=1)
            frame = frames[0]
        else:
            # return source
            return os.path.basename(source)
        # segmentation
        segmentation = SegmentAnything()
        mask = segmentation.draw_mask(predictor=predictor, session=session, frame=frame, point_list=point_list)
        # save mask in tmp?
        mask_file_name = save_colored_mask_cv2(TMP_FOLDER, mask)
        return mask_file_name
