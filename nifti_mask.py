#author @t_sanf

import pandas as pd
from skimage import draw
import numpy as np
np.set_printoptions(threshold=np.inf)

from parsing_VOI import *
import pydicom
import math
import nibabel
import re
import dicom2nifti
import shutil

class VOI_to_nifti_mask(ParseVOI):

    def __init__(self):
        self.anonymize_database = r''
        self.databases=['']


    def create_masks_all_patients(self):
        '''
        create masks for all filestypes for all patients, saves as .nii files
        '''

        databases=self.databases
        segmentation_types=['wp','cz','tz']
        exception_logger=[]

        for database in databases:
            filelist = sorted(self.check_complete_mask(database))
            print('total of {} files left to convert'.format(len(filelist)))
            for patient_dir in filelist:
                print("converting files to mask for patient {}".format(patient_dir))
                voi_files = os.listdir(os.path.join(self.anonymize_database, database, patient_dir, 'voi'))
                for filetype in segmentation_types:
                    print(filetype)

                    #use regular expressions to account for differences in capitalization, search entire string
                    if filetype=='PIRADS':
                        pat=re.compile('([Pp][Ii][Rr][Aa][Dd][Ss]){1}')
                    if filetype=='wp':
                        pat = re.compile('([Ww][Pp]){1}')
                    if filetype=='tz':
                        pat = re.compile('([Tt][Zz]){1}')
                    if filetype=='cz':
                        pat = re.compile('([Cc][Zz]){1}')
                    if filetype=='urethra':
                        pat=re.compile('([Uu][Rr][Ee][Tt][Hh][Rr][Aa]){1}')

                    for file in voi_files:
                        if file.endswith('.voi') and pat.search(file) !=None:
                            try:
                                self.create_nifti_mask(database=database, patient_dir=patient_dir, type=file)

                            except:
                                print("cannot convert file {} for patient {}".format(file,patient_dir))
                                exception_logger+=[patient_dir+'_'+file]

            print("all files cannot be converted: {}".format(exception_logger))
            return exception_logger


    def check_complete_mask(self,database):
        '''check for patient than need nifti masks created'''

        need_mask=[]
        for patient in os.listdir(os.path.join(self.anonymize_database,database)):
            if not os.path.exists(os.path.join(self.anonymize_database, database, patient, 'nifti','mask')):
                need_mask+=[patient]
        return need_mask


    def create_nifti_mask(self,database='',patient_dir='',type=''):
        '''
        creates a mask for each filetype, save in nibabel format
        :param patient_dir: name of directory of patient
        :param type: type of input (i.e. wp, PIRADS)
        :return: none, saves data as mask
        '''

        #define paths to various databases
        patient_dir_t2=os.path.join(self.anonymize_database,database,patient_dir,'dicoms','t2')
        nifti_dir=os.path.join(self.anonymize_database,database,patient_dir,'nifti')
        mask_dir = os.path.join(self.anonymize_database, database, patient_dir, 'nifti', 'mask')

        #get all paths of t2 images and order
        all_image_paths=self.get_all_paths_image_dir(patient_dir=patient_dir_t2)
        image_paths_ordered=self.order_dicom(all_image_paths)

        #read in first image to get shape
        ds_1 = pydicom.dcmread(image_paths_ordered[0])
        data_1 = ds_1.pixel_array

        np_array=np.empty([data_1.shape[0],data_1.shape[1]])
        for image in image_paths_ordered:
            ds = pydicom.dcmread(image,force=True)
            data = ds.pixel_array
            np_array=np.dstack((np_array,data))

        #initialize empty array
        numpy_array_MRI=np_array[:,:,1:]
        n_shape=numpy_array_MRI.shape
        numpy_mask=np.empty([n_shape[0],n_shape[1],n_shape[2]])

        #iterate over mask and update empty array with mask
        mask_dict = self.mask_coord_dict(database=database,patient_dir=patient_dir,type=type)
        for key in mask_dict.keys():
            numpy_mask[:,:,int(key)]=mask_dict[key]

        #make directories if needed
        if not os.path.exists(nifti_dir):
            os.mkdir(nifti_dir)

        if not os.path.exists(mask_dir):
            os.mkdir(mask_dir)

        #need to save as nifti
        mask_nifti = nibabel.Nifti1Image(numpy_mask, affine=np.eye(4))

        os.chdir(mask_dir)
        nibabel.save(mask_nifti,type.split('.')[0]+'.nii')


    def mask_coord_dict(self,database='',patient_dir='',type=''):
        '''
        creates a dictionary where keys are slice number and values are a mask (value 1) for area
        contained within .voi polygon segmentation
        :param patient_dir: root for directory to each patient
        :param type: types of file (wp,tz,urethra,PIRADS)
        :return: dictionary where keys are slice number, values are mask
        '''

        # define path to voi file
        voi_path=os.path.join(self.anonymize_database,database,patient_dir,'voi',type)

        #read in .voi file as pandas df
        pd_df = pd.read_fwf(voi_path)

        # use get_ROI_slice_loc to find location of each segment
        dict=self.get_ROI_slice_loc(voi_path)
        img_shape=self.get_image_size(patient_dir=os.path.join(self.anonymize_database,database,patient_dir))

        output_dict={}
        for slice in dict.keys():
            values=dict[slice]
            select_val=list(range(values[1],values[2]))
            specific_part=pd_df.iloc[select_val,:]
            split_df = specific_part.join(specific_part['MIPAV VOI FILE'].str.split(' ', 1, expand=True).rename(columns={0: "X", 1: "Y"})).drop(['MIPAV VOI FILE'], axis=1)
            X_coord=np.array(split_df['X'].tolist(),dtype=float).astype(int)
            Y_coord=np.array(split_df['Y'].tolist(),dtype=float).astype(int)
            mask=self.poly2mask(vertex_row_coords=X_coord, vertex_col_coords=Y_coord, shape=img_shape)
            output_dict[slice]=mask

        return(output_dict)


    def get_image_size(self,patient_dir=''):
        '''helper function that takes input of root directory for a patient and outputs a nxn size of image
        :param patient_dir- root directory for each patient
        return shape of image (num pixels in x and y directions)
        '''

        #get path to first image in each directory
        patient_dir_full=os.path.join(patient_dir,'dicoms','t2')
        directory=os.path.join(patient_dir_full,os.listdir(os.path.join(patient_dir_full))[0])

        #read in data and get shape
        ds = pydicom.dcmread(directory,force=True)
        data = ds.pixel_array
        return(data.shape)


    def get_all_paths_image_dir(self,patient_dir=''):
        '''
        get all the paths of images in a directory
        :return:
        '''
        #get path to first image in each directory
        all_paths=[os.path.join(patient_dir,file) for file in os.listdir(os.path.join(patient_dir))]
        return all_paths

    def poly2mask(self,vertex_row_coords, vertex_col_coords, shape):
        ''''''
        fill_row_coords, fill_col_coords = draw.polygon(vertex_row_coords, vertex_col_coords, shape)
        mask = np.zeros(shape, dtype=np.int)
        mask[fill_row_coords, fill_col_coords] = 1
        return mask

    def order_dicom(self,dicom_file_list):
        '''
        As input, this method takes a list of paths to dicom directories (from find_dicom_paths), loads dicom, then orders them
        :param dicom_file_list
        :return list of files in correct order
        '''
        dicoms={}
        for path in dicom_file_list:
            file=path
            ds=pydicom.read_file(path,force=True)
            dicoms[str(file)] = float(ds.SliceLocation)
        updated_imagelist=[key for (key, value) in sorted(dicoms.items(), key=lambda x: x[1])]
        return(updated_imagelist)




if __name__=='__main__':
    c=VOI_to_nifti_mask()
    c.create_masks_all_patients()


